"""Execute one upstream gallery source as a real isolated script."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from . import HARNESS_VERSION
from .behavior import GATED_BEHAVIORS
from .contract import REPO_ROOT
from .integrity import aggregate_fallback_state
from .rewrite import rewrite_pyplot_imports


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pdf_page_count(data: bytes) -> int:
    """Read the root page-tree count emitted by Matplotlib's PDF backend."""

    page_tree_counts: list[int] = []
    for page_tree in re.finditer(rb"<<(?:(?!>>).)*>>", data, re.S):
        dictionary = page_tree.group()
        if re.search(rb"/Type\s*/Pages\b", dictionary) is None:
            continue
        count = re.search(rb"/Count\s+(\d+)\b", dictionary)
        if count is not None:
            page_tree_counts.append(int(count.group(1)))
    if page_tree_counts:
        return max(page_tree_counts)
    # Conservative fallback for simple PDFs whose page tree is encoded in an
    # unexpected dictionary order. ``/Page\b`` deliberately excludes
    # ``/Pages``.
    return len(re.findall(rb"/Type\s*/Page\b", data))


def _expected_child_capture_count(extended_requirements: dict[str, Any]) -> int | None:
    expected_outputs = extended_requirements.get("expected_outputs", [])
    if not isinstance(expected_outputs, list):
        return None
    counts = [
        int(output.get("count", 1))
        for output in expected_outputs
        if isinstance(output, dict)
        and output.get("kind") == "figure"
        and output.get("process") == "child"
    ]
    return sum(counts) if counts else None


def _merge_child_process_results(
    result: dict[str, Any],
    *,
    output_dir: Path,
    extended_requirements: dict[str, Any],
) -> None:
    """Promote complete child-process captures into the owning case result."""

    expected_count = _expected_child_capture_count(extended_requirements)
    if expected_count is None:
        return

    child_records: list[dict[str, Any]] = []
    complete_results: list[dict[str, Any]] = []
    for child_path in sorted(output_dir.glob("child-result-*.json")):
        try:
            child_result = json.loads(child_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            child_records.append(
                {
                    "file": child_path.name,
                    "status": "invalid",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        timer_show = child_result.get("extended_driver", {}).get("timer_show", {})
        complete = (
            child_result.get("status") == "passed"
            and isinstance(timer_show, dict)
            and timer_show.get("status") == "passed"
        )
        child_records.append(
            {
                "file": child_path.name,
                "pid": child_result.get("current_pid"),
                "status": child_result.get("status"),
                "capture_count": child_result.get("capture_count", 0),
                "timer_show_status": (
                    timer_show.get("status") if isinstance(timer_show, dict) else None
                ),
                "complete": complete,
            }
        )
        if complete:
            complete_results.append(child_result)

    result["child_processes"] = child_records
    if not complete_results:
        if result.get("status") == "passed":
            result.update(
                {
                    "status": "harness_error",
                    "exception_type": "MissingChildResult",
                    "exception_message": (
                        "no child process completed the timer-driven show protocol"
                    ),
                }
            )
        return

    captures: list[dict[str, Any]] = []
    for child_result in complete_results:
        for capture in child_result.get("captures", []):
            if not isinstance(capture, dict):
                continue
            promoted = dict(capture)
            promoted["sequence"] = len(captures)
            promoted["process"] = "child"
            promoted["process_pid"] = child_result.get("current_pid")
            captures.append(promoted)
    result["captures"] = captures
    result["capture_count"] = len(captures)
    result["capture_errors"] = [
        *result.get("capture_errors", []),
        *[
            str(error)
            for child_result in complete_results
            for error in child_result.get("capture_errors", [])
        ],
    ]
    result["warnings"] = [
        *result.get("warnings", []),
        *[
            warning
            for child_result in complete_results
            for warning in child_result.get("warnings", [])
        ],
    ]
    result["fallback_used"] = aggregate_fallback_state(captures)
    if len(complete_results) == 1:
        child_result = complete_results[0]
        result["behavior"] = child_result.get("behavior", result.get("behavior"))
        extended_driver = dict(result.get("extended_driver", {}))
        extended_driver.update(child_result.get("extended_driver", {}))
        result["extended_driver"] = extended_driver

    if len(captures) != expected_count and result.get("status") == "passed":
        result.update(
            {
                "status": "harness_error",
                "exception_type": "ChildCaptureCountMismatch",
                "exception_message": (
                    f"expected {expected_count} child capture(s), found {len(captures)}"
                ),
            }
        )


def _insertion_offset(source: str) -> int:
    """Insert instrumentation after a docstring and any future imports."""

    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    end_line = 0
    for index, node in enumerate(tree.body):
        is_docstring = (
            index == 0
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
        is_future = isinstance(node, ast.ImportFrom) and node.module == "__future__"
        if not is_docstring and not is_future:
            break
        end_line = int(node.end_lineno or node.lineno)
    return sum(len(line) for line in lines[:end_line])


def _instrumented_source(
    source: str,
    *,
    engine: str,
    output_dir: Path,
    source_path: Path,
    source_sha256: str,
    transformed_sha256: str,
    rewrite_count: int,
    behavior_requirements: tuple[str, ...],
    extended_requirements: dict[str, Any],
) -> str:
    driver = extended_requirements.get("driver", {})
    start_method = driver.get("multiprocessing_start_method") if isinstance(driver, dict) else None
    multiprocessing_bootstrap = (
        "    import multiprocessing as __xy_gallery_multiprocessing\n"
        "    __xy_gallery_multiprocessing.set_start_method("
        f"{start_method!r}, force=True)\n"
        if isinstance(start_method, str)
        else ""
    )
    bootstrap = (
        "\n# --- xy pyplot gallery harness (not part of the upstream source) ---\n"
        'if __name__ == "__main__":\n'
        f"{multiprocessing_bootstrap}"
        "    from scripts.pyplot_gallery.runtime import activate as __xy_gallery_activate\n"
        "    __xy_gallery_runtime = __xy_gallery_activate(\n"
        f"        engine={engine!r},\n"
        f"        output_dir={str(output_dir)!r},\n"
        f"        source_path={str(source_path)!r},\n"
        f"        source_sha256={source_sha256!r},\n"
        f"        transformed_sha256={transformed_sha256!r},\n"
        f"        rewrite_count={rewrite_count!r},\n"
        f"        behavior_requirements={behavior_requirements!r},\n"
        f"        extended_requirements={extended_requirements!r},\n"
        "    )\n"
        "    import sys as __xy_gallery_sys\n"
        f"    __xy_gallery_source_dir = {str(source_path.parent)!r}\n"
        "    if __xy_gallery_source_dir not in __xy_gallery_sys.path:\n"
        "        __xy_gallery_sys.path.append(__xy_gallery_source_dir)\n"
        "# --- end xy pyplot gallery harness ---\n\n"
    )
    footer = (
        "\n\n# --- xy pyplot gallery final capture ---\n"
        'if __name__ == "__main__":\n'
        "    __xy_gallery_runtime.finish(globals())\n"
        "# --- end xy pyplot gallery final capture ---\n"
    )
    offset = _insertion_offset(source)
    return source[:offset] + bootstrap + source[offset:] + footer


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=2)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)


def run_case(
    *,
    engine: str,
    source_path: Path,
    output_dir: Path,
    timeout: float,
    python: Path,
    mplconfig_dir: Path | None = None,
    behavior_requirements: tuple[str, ...] = (),
    extended_requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one engine and return its machine-readable result."""

    source_path = source_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_bytes = source_path.read_bytes()
    source = source_bytes.decode("utf-8")
    source_sha256 = _sha256(source_bytes)
    if engine == "xy":
        rewrite = rewrite_pyplot_imports(source, filename=str(source_path))
        transformed = rewrite.source
        rewrite_count = rewrite.import_count
    elif engine == "matplotlib":
        ast.parse(source, filename=str(source_path))
        transformed = source
        rewrite_count = 0
    else:
        raise ValueError(f"unsupported engine: {engine}")
    transformed_sha256 = _sha256(transformed.encode())
    extended_requirements = extended_requirements or {}
    stale_artifacts = [
        output_dir / "result.json",
        *output_dir.glob("capture-*.png"),
        *output_dir.glob("child-*-capture-*.png"),
        *output_dir.glob("child-result-*.json"),
    ]
    for expected in extended_requirements.get("expected_outputs", []):
        if not isinstance(expected, dict):
            continue
        relative = expected.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute():
            continue
        candidate = (output_dir / relative).resolve()
        if candidate.is_relative_to(output_dir):
            stale_artifacts.append(candidate)
    for artifact in stale_artifacts:
        with suppress(FileNotFoundError):
            artifact.unlink()

    execution_dir = output_dir / "_execution"
    execution_dir.mkdir(exist_ok=True)
    execution_path = execution_dir / source_path.name
    execution_path.write_text(
        _instrumented_source(
            transformed,
            engine=engine,
            output_dir=output_dir,
            source_path=source_path,
            source_sha256=source_sha256,
            transformed_sha256=transformed_sha256,
            rewrite_count=rewrite_count,
            behavior_requirements=behavior_requirements,
            extended_requirements=extended_requirements,
        ),
        encoding="utf-8",
    )
    stdout_path = output_dir / "stdout.txt"
    stderr_path = output_dir / "stderr.txt"
    backends = extended_requirements.get("backends", {})
    requested_backend = str(backends.get(engine, "Agg")) if isinstance(backends, dict) else "Agg"
    argv = extended_requirements.get("argv", [])
    if not isinstance(argv, list) or not all(isinstance(argument, str) for argument in argv):
        raise ValueError("extended gallery argv must be a list of strings")
    environment = {
        **os.environ,
        "MPLBACKEND": requested_backend,
        "MPLCONFIGDIR": str(
            mplconfig_dir or os.environ.get("MPLCONFIGDIR") or output_dir / ".mplconfig"
        ),
        "PYTHONHASHSEED": "0",
        # The corpus contains shapes_and_collections/collections.py. Without
        # safe-path startup, the temporary script directory becomes
        # sys.path[0] and that file shadows stdlib collections before the
        # runtime bootstrap can import. The bootstrap deliberately appends the
        # original source directory later, after the interpreter is healthy.
        "PYTHONSAFEPATH": "1",
        "PYTHONUNBUFFERED": "1",
        "QT_QPA_PLATFORM": "offscreen",
        "TK_SILENCE_DEPRECATION": "1",
    }
    if engine == "xy":
        environment["XY_PYPLOT_MODE"] = "compat"
    # Never expose the gallery directory during interpreter startup. The
    # upstream shapes_and_collections/collections.py would otherwise shadow
    # stdlib collections before even json/runtime can import. The bootstrap
    # appends the directory only after those modules are safely initialized.
    search_paths = [str(REPO_ROOT)]
    if environment.get("PYTHONPATH"):
        search_paths.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(search_paths)

    started = time.monotonic()
    with (
        stdout_path.open("w", encoding="utf-8") as stdout,
        stderr_path.open("w", encoding="utf-8") as stderr,
    ):
        process = subprocess.Popen(
            [str(python), "-P", str(execution_path), *argv],
            cwd=output_dir,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            text=True,
            start_new_session=True,
        )
        timed_out = False
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_group(process)
            returncode = process.returncode

    result_path = output_dir / "result.json"
    if result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        result = {
            "schema_version": 2,
            "harness_version": HARNESS_VERSION,
            "engine": engine,
            "source": str(source_path),
            "source_sha256": source_sha256,
            "transformed_sha256": transformed_sha256,
            "rewrite_count": rewrite_count,
            "ast_rewrite_verified": engine == "matplotlib" or rewrite_count > 0,
            "status": "error",
            "exception_type": "MissingResult",
            "exception_message": (
                "script exited before the gallery runtime wrote result.json "
                f"(process status {returncode})"
            ),
            "capture_count": 0,
            "captures": [],
            "warnings": [],
            "capture_errors": [],
            "behavior_requirements": list(behavior_requirements),
            "behavior": {
                "required": sorted(set(behavior_requirements) & GATED_BEHAVIORS),
                "status": "missing",
                "errors": ["script exited before behavior evidence was recorded"],
            },
        }
    if timed_out:
        result.update(
            {
                "status": "timeout",
                "exception_type": "TimeoutExpired",
                "exception_message": f"case exceeded {timeout:g} seconds",
            }
        )
    elif returncode and result.get("status") in {None, "passed", "running"}:
        result.update(
            {
                "status": "error",
                "exception_type": "ProcessExit",
                "exception_message": f"script exited with status {returncode}",
            }
        )
    elif not returncode and result.get("status") in {None, "running"}:
        result.update(
            {
                "status": "harness_error",
                "exception_type": "MissingTerminalStatus",
                "exception_message": "script exited without a terminal gallery status",
            }
        )
    _merge_child_process_results(
        result,
        output_dir=output_dir,
        extended_requirements=extended_requirements,
    )
    result.update(
        {
            "returncode": returncode,
            "wall_duration_seconds": round(time.monotonic() - started, 6),
            "stdout": stdout_path.name,
            "stderr": stderr_path.name,
            "stdout_sha256": _sha256(stdout_path.read_bytes()),
            "stderr_sha256": _sha256(stderr_path.read_bytes()),
            "requested_matplotlib_backend": requested_backend,
            "extended_requirements": extended_requirements or None,
        }
    )
    output_artifacts: list[dict[str, Any]] = []
    for expected in extended_requirements.get("expected_outputs", []):
        if not isinstance(expected, dict) or expected.get("kind") != "pdf":
            continue
        relative = expected.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute():
            continue
        artifact_path = output_dir / relative
        if not artifact_path.is_file():
            continue
        data = artifact_path.read_bytes()
        output_artifacts.append(
            {
                "kind": "pdf",
                "path": relative,
                "byte_count": len(data),
                "sha256": _sha256(data),
                "page_count": _pdf_page_count(data),
            }
        )
    result["output_artifacts"] = output_artifacts
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("matplotlib", "xy"), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument(
        "--mplconfig-dir",
        type=Path,
        help="shared, prewarmed Matplotlib config/cache directory",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="interpreter used for the real temporary script",
    )
    args = parser.parse_args()
    result = run_case(
        engine=args.engine,
        source_path=args.source,
        output_dir=args.output,
        timeout=args.timeout,
        python=args.python,
        mplconfig_dir=args.mplconfig_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
