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

import pytest

from xy.pyplot._translate import check_unsupported, not_implemented

PACKAGE = Path(__file__).resolve().parents[2] / "python" / "xy"
SUPPORT_REQUEST_URL = "https://github.com/reflex-dev/xy/issues"


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


def test_unsupported_errors_link_to_support_requests() -> None:
    assert str(not_implemented("polar charts")) == (
        "xy.pyplot does not implement polar charts. See the compatibility table: "
        "https://github.com/reflex-dev/xy/blob/main/spec/matplotlib/compat.md. "
        f"Request support: {SUPPORT_REQUEST_URL}"
    )
    with pytest.raises(TypeError) as exc_info:
        check_unsupported({"projection": "polar"}, "subplot()")
    assert str(exc_info.value) == (
        "xy.pyplot subplot() got unsupported keyword(s): projection. "
        "See the compatibility table: "
        "https://github.com/reflex-dev/xy/blob/main/spec/matplotlib/compat.md. "
        f"Request support: {SUPPORT_REQUEST_URL}"
    )


def test_complete_supported_corpus_runs_when_matplotlib_imports_fail() -> None:
    """Every advertised plotting method remains usable in dependency-free installs."""
    corpus = Path(__file__).with_name("corpus")
    _run_fresh(
        f"""
        import builtins
        import pathlib
        import runpy

        real_import = builtins.__import__
        def blocked_import(name, *args, **kwargs):
            if name == "matplotlib" or name.startswith("matplotlib."):
                raise ImportError("matplotlib intentionally unavailable")
            return real_import(name, *args, **kwargs)
        builtins.__import__ = blocked_import

        import xy.pyplot as plt
        for path in sorted(pathlib.Path({str(corpus)!r}).glob("[0-9][0-9]_*.py")):
            runpy.run_path(path, run_name="__main__")
            for figure in tuple(__import__("xy.pyplot._state", fromlist=["all_figures"]).all_figures()):
                assert figure._repr_html_().startswith('<iframe class="xy-notebook-frame"')
            plt.close("all")
        """
    )
