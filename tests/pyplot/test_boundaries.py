"""Containment guardrails: the shim is one folder, and the dependency points
one way. These keep the constraint structural — a future engine change that
imports the shim, or a shim change that drags in heavy imports, fails CI."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "python" / "xy"


def _run_fresh(code: str) -> None:
    subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        check=True,
        capture_output=True,
        env=os.environ.copy(),
        text=True,
    )


def test_core_never_imports_the_shim() -> None:
    """No module outside python/xy/pyplot/ may reference it."""
    offenders: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        if "pyplot" in path.parts:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [module] + [f"{module}.{a.name}" for a in node.names]
                if node.level and "pyplot" in names:
                    offenders.append(f"{path}: relative import of pyplot")
            else:
                continue
            if any("pyplot" in n for n in names):
                offenders.append(f"{path}: {names}")
    assert offenders == [], offenders


def test_importing_xy_does_not_load_the_shim() -> None:
    _run_fresh(
        """
        import sys
        import xy
        assert not any("pyplot" in name for name in sys.modules), [
            n for n in sys.modules if "pyplot" in n
        ]
        """
    )


def test_shim_import_stays_light() -> None:
    """The shim must not load the widget stack — and obviously not matplotlib."""
    _run_fresh(
        """
        import sys
        import xy.pyplot as plt
        assert "matplotlib" not in sys.modules
        assert "xy.widget" not in sys.modules
        assert "anywidget" not in sys.modules
        assert "traitlets" not in sys.modules
        assert callable(plt.plot)
        """
    )


def test_shim_never_imports_real_matplotlib_statically() -> None:
    shim = PACKAGE / "pyplot"
    for path in shim.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(a.name.split(".")[0] == "matplotlib" for a in node.names), path
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] != "matplotlib", path
