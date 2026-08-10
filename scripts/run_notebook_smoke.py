#!/usr/bin/env python3
"""Execute a bounded public-notebook smoke suite.

The public examples include notebooks that intentionally download large remote
datasets. This runner keeps the PR gate deterministic by selecting a small
representative set and pre-seeding the real-world notebook cache with fixture
data before executing its cells.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import re
import signal
import sys
import tempfile
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ORACLE = ROOT / "scripts" / "notebook_smoke_pr_oracle.json"
ORACLE_OUTPUT_KEYS = {"kind", "sha256", "size"}
DISPLAY_OUTPUT_KINDS = {"repr", "_repr_mimebundle_", "_repr_html_", "_repr_svg_", "_repr_png_"}
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class NotebookCase:
    name: str
    path: Path
    env: dict[str, str]


@dataclass(frozen=True)
class DisplayOutput:
    kind: str
    sha256: str
    size: int

    def as_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "sha256": self.sha256, "size": self.size}


@dataclass(frozen=True)
class NotebookResult:
    code_cells: int
    display_outputs: int
    outputs: tuple[DisplayOutput, ...] = field(default=(), compare=False, repr=False)


@dataclass(frozen=True)
class CellResult:
    outputs: tuple[DisplayOutput, ...]
    displayed_ids: frozenset[int]


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
    if seconds <= 0:
        raise ValueError("notebook cell timeout must be positive")
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


def _validate_kernelspec(case: NotebookCase, notebook: dict[str, object]) -> None:
    metadata = notebook.get("metadata", {})
    kernelspec = metadata.get("kernelspec", {}) if isinstance(metadata, dict) else {}
    if not isinstance(kernelspec, dict):
        raise ValueError(f"{case.name}: metadata.kernelspec must be a mapping")
    name = kernelspec.get("name")
    language = kernelspec.get("language")
    if name not in {"python", "python3"} or language != "python":
        raise ValueError(f"{case.name}: unsupported kernelspec {kernelspec!r}; expected Python 3")


def _stable_display_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except TypeError:
        return repr(value).encode("utf-8")


def _display_output(kind: str, payload: object) -> DisplayOutput:
    if kind == "repr":
        payload = re.sub(r"0x[0-9a-fA-F]+", "0x...", str(payload))
    data = _stable_display_bytes(payload)
    return DisplayOutput(kind=kind, sha256=hashlib.sha256(data).hexdigest(), size=len(data))


def _render_display_value(value: object) -> DisplayOutput | None:
    if value is None:
        return None
    for method_name in ("_repr_mimebundle_", "_repr_html_", "_repr_svg_", "_repr_png_"):
        method = getattr(value, method_name, None)
        if callable(method):
            return _display_output(method_name, method())
    return _display_output("repr", repr(value))


def _execute_cell(source: str, filename: str, namespace: dict[str, object]) -> CellResult:
    module = ast.parse(source, filename=filename, mode="exec")
    if module.body and isinstance(module.body[-1], ast.Expr) and not source.rstrip().endswith(";"):
        prefix = ast.Module(body=module.body[:-1], type_ignores=module.type_ignores)
        ast.fix_missing_locations(prefix)
        exec(compile(prefix, filename, "exec"), namespace)
        value = eval(compile(ast.Expression(module.body[-1].value), filename, "eval"), namespace)
        output = _render_display_value(value)
        return CellResult(
            (() if output is None else (output,)),
            frozenset({id(value)} if output is not None else ()),
        )
    exec(compile(module, filename, "exec"), namespace)
    return CellResult((), frozenset())


def _close_matplotlib_figures() -> None:
    pyplot = sys.modules.get("matplotlib.pyplot")
    close = getattr(pyplot, "close", None) if pyplot is not None else None
    if callable(close):
        close("all")


def _flush_xy_pyplot_figures(*, skip_ids: frozenset[int]) -> tuple[DisplayOutput, ...]:
    pyplot = sys.modules.get("xy.pyplot")
    if pyplot is None:
        _close_matplotlib_figures()
        return ()
    all_figures = getattr(pyplot, "all_figures", None)
    close = getattr(pyplot, "close", None)
    if not callable(all_figures) or not callable(close):
        _close_matplotlib_figures()
        return ()
    figures = list(all_figures())
    outputs = tuple(
        output
        for figure in figures
        if id(figure) not in skip_ids
        for output in (_render_display_value(figure),)
        if output is not None
    )
    if figures:
        close("all")
    _close_matplotlib_figures()
    return outputs


def _validate_oracle_output(
    path: Path,
    case_name: str,
    index: int,
    output: object,
) -> dict[str, object]:
    error = f"notebook smoke oracle {path} has invalid display-output entry {case_name}[{index}]"
    if not isinstance(output, dict) or set(output) != ORACLE_OUTPUT_KEYS:
        raise ValueError(error)
    kind = output["kind"]
    sha256 = output["sha256"]
    size = output["size"]
    if not isinstance(kind, str) or kind not in DISPLAY_OUTPUT_KINDS:
        raise ValueError(error)
    if not isinstance(sha256, str) or SHA256_HEX.fullmatch(sha256) is None:
        raise ValueError(error)
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError(error)
    return {"kind": kind, "sha256": sha256, "size": size}


def _load_oracle(path: Path) -> dict[str, list[dict[str, object]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"notebook smoke oracle {path} must be a mapping")
    oracle: dict[str, list[dict[str, object]]] = {}
    for name, outputs in data.items():
        if not isinstance(name, str) or not isinstance(outputs, list):
            raise ValueError(f"notebook smoke oracle {path} has invalid entry {name!r}")
        oracle[name] = [
            _validate_oracle_output(path, name, index, output)
            for index, output in enumerate(outputs)
        ]
    return oracle


def _assert_display_outputs_match(
    case: NotebookCase,
    actual_outputs: tuple[DisplayOutput, ...],
    expected_outputs: list[dict[str, object]],
) -> None:
    actual = [output.as_dict() for output in actual_outputs]
    if actual == expected_outputs:
        return
    raise AssertionError(
        f"{case.name}: display output drift\n"
        f"expected: {json.dumps(expected_outputs, sort_keys=True)}\n"
        f"actual: {json.dumps(actual, sort_keys=True)}"
    )


def _execute_notebook(
    case: NotebookCase,
    *,
    cell_timeout: int,
    expected_outputs: list[dict[str, object]] | None = None,
) -> NotebookResult:
    notebook = json.loads(case.path.read_text(encoding="utf-8"))
    _validate_kernelspec(case, notebook)
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
    display_outputs: list[DisplayOutput] = []
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
                        result = _execute_cell(source, filename, namespace)
                        display_outputs.extend(result.outputs)
                        display_outputs.extend(
                            _flush_xy_pyplot_figures(skip_ids=result.displayed_ids)
                        )
                except Exception as exc:
                    print(
                        f"FAIL {case.name}: {filename}: {exc.__class__.__name__}: {exc}",
                        file=sys.stderr,
                    )
                    traceback.print_exc()
                    raise
        finally:
            os.chdir(old_cwd)
    captured_outputs = tuple(display_outputs)
    if expected_outputs is not None:
        _assert_display_outputs_match(case, captured_outputs, expected_outputs)
    elapsed = time.monotonic() - started
    print(
        f"PASS {case.name}: {len(code_cells)} code cells, "
        f"{len(captured_outputs)} display outputs in {elapsed:.2f}s"
    )
    return NotebookResult(len(code_cells), len(captured_outputs), captured_outputs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=["pr"],
        default="pr",
        help="Notebook profile to execute.",
    )
    parser.add_argument("--cell-timeout", type=int, default=60)
    parser.add_argument("--oracle", type=Path, default=DEFAULT_ORACLE)
    parser.add_argument(
        "--update-oracle",
        action="store_true",
        help="Rewrite the smoke profile display-output oracle from the current run.",
    )
    args = parser.parse_args(argv)

    oracle = {} if args.update_oracle else _load_oracle(args.oracle)
    updated_oracle: dict[str, list[dict[str, object]]] = {}
    with tempfile.TemporaryDirectory(prefix="xy-notebook-smoke-") as tmp:
        for case in smoke_cases(Path(tmp)):
            expected_outputs = None
            if not args.update_oracle:
                expected_outputs = oracle.get(case.name)
                if expected_outputs is None:
                    raise ValueError(f"notebook smoke oracle missing case {case.name!r}")
            result = _execute_notebook(
                case,
                cell_timeout=args.cell_timeout,
                expected_outputs=expected_outputs,
            )
            updated_oracle[case.name] = [output.as_dict() for output in result.outputs]
    if args.update_oracle:
        args.oracle.write_text(
            json.dumps(updated_oracle, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Updated notebook smoke oracle: {args.oracle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
