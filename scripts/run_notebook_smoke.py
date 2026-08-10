#!/usr/bin/env python3
"""Execute a bounded public-notebook smoke suite.

The public examples include notebooks that intentionally download large remote
datasets. This runner keeps the PR gate deterministic by selecting a small
representative set and pre-seeding the real-world notebook cache with fixture
data before executing its cells.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import sys
import tempfile
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class NotebookCase:
    name: str
    path: Path
    env: dict[str, str]


def _write_gaia_fixture(data_dir: Path, rows: int) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / f"gaia-dr3-hr-{rows}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["bp_rp", "phot_g_mean_mag", "parallax"])
        for index in range(rows):
            color = -0.25 + index * (2.6 / max(1, rows - 1))
            magnitude = 5.8 + (index % 9) * 0.4
            parallax = 4.0 + (index % 7) * 0.8
            writer.writerow([f"{color:.6f}", f"{magnitude:.6f}", f"{parallax:.6f}"])


def smoke_cases(tmp_dir: Path) -> list[NotebookCase]:
    gaia_rows = 32
    gaia_data = tmp_dir / "gaia"
    _write_gaia_fixture(gaia_data, gaia_rows)
    common_env = {
        "MPLBACKEND": "Agg",
        "XY_NOTEBOOK_DISPLAY": "html",
        "XY_REAL_WORLD_DATA": str(gaia_data),
        "GAIA_ROWS": str(gaia_rows),
    }
    return [
        NotebookCase(
            "basic-xy",
            ROOT / "examples" / "symlog_axis.ipynb",
            common_env,
        ),
        NotebookCase(
            "pdsh-matplotlib-shim",
            ROOT / "examples" / "pdsh" / "pdsh_04_01_simple_line_plots.ipynb",
            common_env,
        ),
        NotebookCase(
            "real-world-gaia-reduced",
            ROOT / "examples" / "real_world" / "01_gaia_hr_diagram.ipynb",
            common_env,
        ),
    ]


@contextmanager
def _patched_environment(values: dict[str, str]) -> Iterator[None]:
    old = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _cell_timeout(seconds: int) -> Iterator[None]:
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def fail(_signum: int, _frame: FrameType | None) -> None:
        raise TimeoutError(f"notebook cell exceeded {seconds}s")

    previous = signal.signal(signal.SIGALRM, fail)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _execute_notebook(case: NotebookCase, *, cell_timeout: int) -> None:
    notebook = json.loads(case.path.read_text(encoding="utf-8"))
    try:
        display_path = case.path.relative_to(ROOT)
    except ValueError:
        display_path = case.path
    namespace: dict[str, object] = {
        "__name__": "__main__",
        "__file__": str(case.path),
    }
    started = time.monotonic()
    code_cells = [
        (index, "".join(cell.get("source", [])))
        for index, cell in enumerate(notebook.get("cells", []), start=1)
        if cell.get("cell_type") == "code"
    ]
    with _patched_environment(case.env):
        old_cwd = Path.cwd()
        os.chdir(ROOT)
        try:
            for index, source in code_cells:
                if not source.strip():
                    continue
                filename = f"{display_path}:cell-{index}"
                try:
                    with _cell_timeout(cell_timeout):
                        exec(compile(source, filename, "exec"), namespace)
                except Exception as exc:
                    print(
                        f"FAIL {case.name}: {filename}: {exc.__class__.__name__}: {exc}",
                        file=sys.stderr,
                    )
                    traceback.print_exc()
                    raise
        finally:
            os.chdir(old_cwd)
    elapsed = time.monotonic() - started
    print(f"PASS {case.name}: {len(code_cells)} code cells in {elapsed:.2f}s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=["pr"],
        default="pr",
        help="Notebook profile to execute.",
    )
    parser.add_argument("--cell-timeout", type=int, default=60)
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="xy-notebook-smoke-") as tmp:
        for case in smoke_cases(Path(tmp)):
            _execute_notebook(case, cell_timeout=args.cell_timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
