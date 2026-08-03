"""Run a deterministic shard of the vendored differential gallery."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageEnhance

from . import HARNESS_VERSION
from .behavior import GATED_BEHAVIORS, behavior_gate
from .contract import BASELINE_PATH, CORPUS_ROOT, MANIFEST_PATH, REPO_ROOT
from .extended_environment import SPEC_PATH as EXTENDED_SPEC_PATH
from .extended_environment import load_spec
from .integrity import capture_background, capture_integrity_errors
from .metrics import (
    compare_images,
    compare_semantics,
    evaluate_dimensions,
    evaluate_visual,
    metrics_dict,
)
from .provenance import query_python_interpreter
from .run_case import run_case


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class _RepositorySnapshot:
    """Git state at one boundary of a gallery run."""

    head: str | None
    dirty: bool | None


def _repository_head(repo_root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        return None
    return completed.stdout.strip() or None


def _relative_output_root(output_root: Path, repo_root: Path) -> str | None:
    """Return a strict repo-relative output directory, if there is one."""

    try:
        relative = output_root.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return None
    if not relative.parts:
        # Selecting the repository itself cannot safely suppress every change.
        return None
    return relative.as_posix()


def _ignored_status_path(path: str, output_relative: str | None) -> bool:
    if path == "test.png":
        return True
    return bool(
        output_relative and (path == output_relative or path.startswith(f"{output_relative}/"))
    )


def _repository_dirty(output_root: Path, repo_root: Path) -> bool | None:
    """Return Git dirtiness outside this run's output and ``test.png``."""

    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        return None
    output_relative = _relative_output_root(output_root, repo_root)
    records = completed.stdout.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2] != " ":
            return True
        status = record[:2]
        paths = [record[3:]]
        if "R" in status or "C" in status:
            if index >= len(records) or not records[index]:
                return True
            paths.append(records[index])
            index += 1
        # A rename wholly inside the output remains an output artifact.  A
        # move across its boundary still exposes the unrelated source/target.
        if not all(_ignored_status_path(path, output_relative) for path in paths):
            return True
    return False


def _repository_snapshot(
    output_root: Path,
    *,
    repo_root: Path | None = None,
) -> _RepositorySnapshot:
    root = REPO_ROOT if repo_root is None else repo_root
    return _RepositorySnapshot(
        head=_repository_head(root),
        dirty=_repository_dirty(output_root, root),
    )


def _implementation_provenance(
    start: _RepositorySnapshot,
    end: _RepositorySnapshot,
) -> tuple[str | None, bool | None]:
    """Resolve a fail-closed commit and clean-tree result for one run."""

    configured = os.environ.get("XY_GALLERY_IMPLEMENTATION_COMMIT", "").strip() or None
    repository_available = any(
        value is not None for value in (start.head, start.dirty, end.head, end.dirty)
    )
    stable_head = start.head if start.head is not None and start.head == end.head else None
    if repository_available:
        implementation_commit = stable_head
        configured_mismatch = configured is not None and (
            start.head != configured or end.head != configured
        )
    else:
        # An sdist has no Git identity.  Keep an explicitly supplied revision
        # visible, but the indeterminate dirty state still prevents promotion.
        implementation_commit = configured
        configured_mismatch = False

    if start.head != end.head or configured_mismatch:
        implementation_dirty: bool | None = True
    elif start.dirty is True or end.dirty is True:
        implementation_dirty = True
    elif start.dirty is False and end.dirty is False:
        implementation_dirty = False
    else:
        implementation_dirty = None
    return implementation_commit, implementation_dirty


def _implementation_commit() -> str | None:
    """Return the authoritative current Git revision, when available."""

    snapshot = _repository_snapshot(REPO_ROOT)
    return _implementation_provenance(snapshot, snapshot)[0]


def _implementation_dirty(output_root: Path | None = None) -> bool | None:
    """Return current dirtiness with an optional runner-output exclusion."""

    snapshot = _repository_snapshot(REPO_ROOT if output_root is None else output_root)
    return _implementation_provenance(snapshot, snapshot)[1]


def _parse_shard(value: str) -> tuple[int, int]:
    try:
        index_text, total_text = value.split("/", 1)
        index, total = int(index_text), int(total_text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("shard must be INDEX/TOTAL") from exc
    if total < 1 or not 0 <= index < total:
        raise argparse.ArgumentTypeError("shard requires TOTAL >= 1 and 0 <= INDEX < TOTAL")
    return index, total


def _in_shard(path: str, shard: tuple[int, int]) -> bool:
    index, total = shard
    digest = hashlib.sha256(path.encode()).digest()
    return int.from_bytes(digest[:8], "big") % total == index


def _artifact_dir(output_root: Path, relative: str, engine: str) -> Path:
    return output_root / "runs" / Path(relative).with_suffix("") / engine


def _resumable_result(
    *,
    output_root: Path,
    entry: dict[str, Any],
    engine: str,
    python_interpreter: dict[str, str],
    extended_requirements: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    artifact_dir = _artifact_dir(output_root, entry["path"], engine)
    result_path = artifact_dir / "result.json"
    if not result_path.is_file():
        return None
    try:
        result = _load(result_path)
    except (OSError, ValueError):
        return None
    if (
        result.get("engine") != engine
        or result.get("harness_version") != HARNESS_VERSION
        or result.get("source_sha256") != entry["sha256"]
        or result.get("status") not in {"passed", "error", "timeout", "harness_error"}
        or (engine == "xy" and result.get("requested_pyplot_mode") != "compat")
        or sorted(result.get("behavior_requirements", [])) != sorted(entry.get("behavior", []))
        or result.get("extended_requirements") != extended_requirements
        or result.get("python_interpreter") != python_interpreter
    ):
        return None
    backends = (extended_requirements or {}).get("backends", {})
    expected_backend = str(backends.get(engine, "Agg")) if isinstance(backends, dict) else "Agg"
    if result.get("requested_matplotlib_backend") != expected_backend:
        return None
    if any(
        not (artifact_dir / capture.get("file", "")).is_file()
        for capture in result.get("captures", [])
    ):
        return None
    return result


def _prewarm_mplconfig(python: Path, mplconfig_dir: Path) -> None:
    """Build one shared font cache before measured cases run in parallel."""

    mplconfig_dir.mkdir(parents=True, exist_ok=True)
    environment = {
        **os.environ,
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": str(mplconfig_dir),
    }
    completed = subprocess.run(
        [
            str(python),
            "-c",
            (
                "import matplotlib; "
                "from matplotlib import font_manager; "
                "font_manager.findfont('DejaVu Sans')"
            ),
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=120,
    )
    if completed.returncode:
        raise RuntimeError(
            "failed to prewarm the shared Matplotlib cache: "
            + (completed.stderr or completed.stdout)
        )


def _difference_image(reference_path: Path, candidate_path: Path, output_path: Path) -> None:
    with (
        Image.open(reference_path).convert("RGBA") as reference,
        Image.open(candidate_path).convert("RGBA") as candidate,
    ):
        size = (max(reference.width, candidate.width), max(reference.height, candidate.height))
        first = Image.new("RGBA", size, "white")
        second = Image.new("RGBA", size, "white")
        first.paste(reference, (0, 0), reference)
        second.paste(candidate, (0, 0), candidate)
        difference = ImageChops.difference(first.convert("RGB"), second.convert("RGB"))
        difference = ImageEnhance.Contrast(difference).enhance(3.0)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        difference.save(output_path)


def _copy_failure_artifacts(
    *,
    output_root: Path,
    relative: str,
    index: int,
    reference_path: Path,
    xy_path: Path,
) -> None:
    target = output_root / "failures" / Path(relative).with_suffix("") / f"figure-{index:03d}"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(reference_path, target / "reference.png")
    shutil.copyfile(xy_path, target / "xy.png")
    _difference_image(reference_path, xy_path, target / "difference.png")


def _pair_results(
    *,
    entry: dict[str, Any],
    results: dict[str, dict[str, Any]],
    output_root: Path,
) -> dict[str, Any]:
    reference = results.get("matplotlib", {})
    xy_result = results.get("xy", {})
    behavior_gates: dict[str, dict[str, Any]] = {}
    for engine, result in results.items():
        passed, reasons = behavior_gate(result, entry["behavior"])
        behavior_gates[engine] = {"passed": passed, "reasons": reasons}
    both_passed = reference.get("status") == "passed" and xy_result.get("status") == "passed"
    reference_captures = reference.get("captures", [])
    xy_captures = xy_result.get("captures", [])
    capture_parity = bool(
        both_passed and reference_captures and len(reference_captures) == len(xy_captures)
    )
    figure_pairs: list[dict[str, Any]] = []
    for index in range(min(len(reference_captures), len(xy_captures))):
        reference_capture = reference_captures[index]
        xy_capture = xy_captures[index]
        reference_path = (
            _artifact_dir(output_root, entry["path"], "matplotlib") / reference_capture["file"]
        )
        xy_path = _artifact_dir(output_root, entry["path"], "xy") / xy_capture["file"]
        reference_background = capture_background(reference_capture)
        xy_background = capture_background(xy_capture)
        background_errors: list[str] = []
        if reference_background is None:
            background_errors.append("reference declared background metadata is invalid")
        if xy_background is None:
            background_errors.append("xy declared background metadata is invalid")
        visual_metrics = compare_images(
            reference_path,
            xy_path,
            reference_background=reference_background or (255, 255, 255),
            xy_background=xy_background or (255, 255, 255),
        )
        visual_gate = evaluate_visual(visual_metrics, entry["render_class"])
        dimension_gate = evaluate_dimensions(
            tuple(visual_metrics.reference_dimensions),
            tuple(visual_metrics.xy_dimensions),
            policy=entry["dimension_policy"],
        )
        semantics = compare_semantics(
            reference_capture.get("semantic", {}),
            xy_capture.get("semantic", {}),
        )
        visual_decision = "fail" if background_errors else visual_gate.decision
        pair = {
            "index": index,
            "metrics": metrics_dict(visual_metrics),
            "visual_gate": {
                "decision": visual_decision,
                "reasons": [*background_errors, *visual_gate.reasons],
            },
            "dimension_gate": {
                "decision": dimension_gate.decision,
                "reasons": list(dimension_gate.reasons),
            },
            "exact_dimensions_match": (
                visual_metrics.reference_dimensions == visual_metrics.xy_dimensions
            ),
            "semantic_differences": semantics,
        }
        figure_pairs.append(pair)
        if visual_decision != "pass" or dimension_gate.decision != "pass" or semantics:
            _copy_failure_artifacts(
                output_root=output_root,
                relative=entry["path"],
                index=index,
                reference_path=reference_path,
                xy_path=xy_path,
            )

    return {
        "capture_parity": capture_parity,
        "exact_dimension_parity": bool(
            capture_parity and all(pair["exact_dimensions_match"] for pair in figure_pairs)
        ),
        "dimension_gate_passed": bool(
            capture_parity
            and figure_pairs
            and all(pair["dimension_gate"]["decision"] == "pass" for pair in figure_pairs)
        ),
        "visual_gate_passed": bool(
            capture_parity
            and figure_pairs
            and all(pair["visual_gate"]["decision"] == "pass" for pair in figure_pairs)
        ),
        "semantic_gate_passed": bool(
            capture_parity
            and figure_pairs
            and all(not pair["semantic_differences"] for pair in figure_pairs)
        ),
        "behavior_gate_passed": bool(
            both_passed
            and behavior_gates.get("matplotlib", {}).get("passed")
            and behavior_gates.get("xy", {}).get("passed")
        ),
        "behavior_gates": behavior_gates,
        "figure_pairs": figure_pairs,
    }


def _ratchet_case(
    *,
    entry: dict[str, Any],
    baseline: dict[str, Any],
    results: dict[str, dict[str, Any]],
    comparison: dict[str, Any],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    path = entry["path"]
    for engine, key in (("matplotlib", "reference"), ("xy", "xy")):
        previous = baseline[key]
        current = results.get(engine, {})
        errors.extend(
            f"{path}: {engine} {reason}" for reason in capture_integrity_errors(engine, current)
        )
        current_behavior_passed, behavior_reasons = behavior_gate(current, entry["behavior"])
        if current.get("status") == "passed" and not current_behavior_passed:
            detail = "; ".join(behavior_reasons) or "no behavior evidence"
            errors.append(f"{path}: {engine} required behavior failed: {detail}")
        if previous["status"] == "passed" and current.get("status") != "passed":
            errors.append(f"{path}: {engine} execution regressed to {current.get('status')}")
        if previous["status"] != "passed" or current.get("status") != "passed":
            continue
        old_duration = float(previous.get("duration_seconds", 0.0))
        new_duration = float(current.get("wall_duration_seconds", 0.0))
        if old_duration > 0 and new_duration > old_duration * 8 + 2:
            errors.append(
                f"{path}: {engine} duration {new_duration:.3f}s exceeds "
                f"8x baseline + 2s ({old_duration:.3f}s)"
            )
        elif old_duration > 0 and new_duration > old_duration * 2 + 0.25:
            warnings.append(
                f"{path}: {engine} duration {new_duration:.3f}s exceeds "
                f"2x baseline + 250ms ({old_duration:.3f}s)"
            )

    if baseline.get("capture_parity") and not comparison["capture_parity"]:
        errors.append(f"{path}: figure/capture parity regressed")
    if baseline.get("dimension_gate_passed") and not comparison["dimension_gate_passed"]:
        errors.append(f"{path}: canvas-dimension acceptance gate regressed")
    if baseline.get("visual_gate_passed") and not comparison["visual_gate_passed"]:
        errors.append(f"{path}: tolerant visual gate regressed")
    if baseline.get("semantic_gate_passed") and not comparison["semantic_gate_passed"]:
        errors.append(f"{path}: semantic gate regressed")
    if baseline.get("behavior_gate_passed") and not comparison["behavior_gate_passed"]:
        errors.append(f"{path}: behavior gate regressed")
    return errors, warnings


def _write_junit(cases: list[dict[str, Any]], output: Path) -> None:
    suite = ET.Element(
        "testsuite",
        {
            "name": "pyplot-gallery",
            "tests": str(len(cases)),
            "failures": str(sum(bool(case["ratchet_errors"]) for case in cases)),
        },
    )
    for case in cases:
        test = ET.SubElement(
            suite,
            "testcase",
            {
                "classname": "matplotlib_gallery",
                "name": case["path"],
            },
        )
        if case["ratchet_errors"]:
            failure = ET.SubElement(test, "failure", {"message": case["ratchet_errors"][0]})
            failure.text = "\n".join(case["ratchet_errors"])
        if case["ratchet_warnings"]:
            output_node = ET.SubElement(test, "system-out")
            output_node.text = "\n".join(case["ratchet_warnings"])
    ET.ElementTree(suite).write(output, encoding="utf-8", xml_declaration=True)


def run_gallery(
    *,
    output_root: Path,
    python: Path,
    timeout: float,
    workers: int,
    profile: str,
    shard: tuple[int, int],
    match: str | None,
    engines: tuple[str, ...],
    resume: bool = False,
    manifest_path: Path = MANIFEST_PATH,
    baseline_path: Path = BASELINE_PATH,
    corpus_root: Path = CORPUS_ROOT,
    extended_spec_path: Path = EXTENDED_SPEC_PATH,
) -> dict[str, Any]:
    repository_start = _repository_snapshot(output_root)
    python_interpreter = query_python_interpreter(python)
    manifest = _load(manifest_path)
    baseline = _load(baseline_path)
    entries = [
        entry
        for entry in manifest["examples"]
        if entry["pyplot_eligible"]
        and (profile == "all" or entry["profile"] == profile)
        and _in_shard(entry["path"], shard)
        and (match is None or match in entry["path"])
    ]
    extended_by_path: dict[str, dict[str, Any]] = {}
    if any(entry["profile"] == "extended" for entry in entries):
        extended_spec = load_spec(extended_spec_path)
        extended_by_path = {
            str(requirements["path"]): requirements for requirements in extended_spec["examples"]
        }
        selected_extended = {entry["path"] for entry in entries if entry["profile"] == "extended"}
        missing_requirements = selected_extended - set(extended_by_path)
        if missing_requirements:
            raise ValueError(
                "extended gallery entries have no environment contract: "
                + ", ".join(sorted(missing_requirements))
            )
    output_root.mkdir(parents=True, exist_ok=True)
    mplconfig_dir = output_root / "_mplconfig"
    _prewarm_mplconfig(python, mplconfig_dir)
    by_path: dict[str, dict[str, dict[str, Any]]] = {entry["path"]: {} for entry in entries}
    jobs: list[tuple[dict[str, Any], str]] = []
    resumed = 0
    for entry in entries:
        for engine in engines:
            result = (
                _resumable_result(
                    output_root=output_root,
                    entry=entry,
                    engine=engine,
                    extended_requirements=extended_by_path.get(entry["path"]),
                    python_interpreter=python_interpreter,
                )
                if resume
                else None
            )
            if result is None:
                jobs.append((entry, engine))
            else:
                by_path[entry["path"]][engine] = result
                resumed += 1
    if resumed:
        print(f"resumed {resumed} completed engine runs", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                run_case,
                engine=engine,
                source_path=corpus_root / "examples" / entry["path"],
                output_dir=_artifact_dir(output_root, entry["path"], engine),
                timeout=min(
                    timeout,
                    float(extended_by_path.get(entry["path"], {}).get("timeout_seconds", timeout)),
                ),
                python=python,
                mplconfig_dir=mplconfig_dir,
                behavior_requirements=tuple(entry["behavior"]),
                extended_requirements=extended_by_path.get(entry["path"]),
            ): (entry, engine)
            for entry, engine in jobs
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            entry, engine = futures[future]
            try:
                result = future.result()
            except BaseException as exc:
                result = {
                    "engine": engine,
                    "status": "harness_error",
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "capture_count": 0,
                    "captures": [],
                }
            by_path[entry["path"]][engine] = result
            print(
                f"[{completed}/{len(jobs)}] {engine} {entry['path']}: "
                f"{result.get('status', 'harness_error')}",
                flush=True,
            )

    cases: list[dict[str, Any]] = []
    for entry in entries:
        results = by_path[entry["path"]]
        comparison = (
            _pair_results(entry=entry, results=results, output_root=output_root)
            if {"matplotlib", "xy"} <= set(results)
            else {
                "capture_parity": False,
                "exact_dimension_parity": False,
                "dimension_gate_passed": False,
                "visual_gate_passed": False,
                "semantic_gate_passed": False,
                "behavior_gate_passed": False,
                "behavior_gates": {
                    engine: {
                        "passed": behavior_gate(result, entry["behavior"])[0],
                        "reasons": behavior_gate(result, entry["behavior"])[1],
                    }
                    for engine, result in results.items()
                },
                "figure_pairs": [],
            }
        )
        errors, performance_warnings = _ratchet_case(
            entry=entry,
            baseline=baseline["examples"][entry["path"]],
            results=results,
            comparison=comparison,
        )
        cases.append(
            {
                "path": entry["path"],
                "profile": entry["profile"],
                "render_class": entry["render_class"],
                "behavior": entry["behavior"],
                "issue": entry["issue"],
                "temporary_waivers": entry["temporary_waivers"],
                "extended_environment": extended_by_path.get(entry["path"]),
                "engines": results,
                "comparison": comparison,
                "ratchet_errors": errors,
                "ratchet_warnings": performance_warnings,
            }
        )

    summary = {
        "selected_examples": len(entries),
        "engine_runs": len(entries) * len(engines),
        "executed_engine_runs": len(jobs),
        "resumed_engine_runs": resumed,
        "matplotlib_passed": sum(
            case["engines"].get("matplotlib", {}).get("status") == "passed" for case in cases
        ),
        "xy_passed": sum(case["engines"].get("xy", {}).get("status") == "passed" for case in cases),
        "capture_parity_passed": sum(case["comparison"]["capture_parity"] for case in cases),
        "dimension_parity_passed": sum(
            case["comparison"]["dimension_gate_passed"] for case in cases
        ),
        "exact_dimension_parity_passed": sum(
            case["comparison"]["exact_dimension_parity"] for case in cases
        ),
        "visual_gate_passed": sum(case["comparison"]["visual_gate_passed"] for case in cases),
        "semantic_gate_passed": sum(case["comparison"]["semantic_gate_passed"] for case in cases),
        "behavior_required": sum(bool(set(case["behavior"]) & GATED_BEHAVIORS) for case in cases),
        "behavior_gate_passed": sum(
            bool(set(case["behavior"]) & GATED_BEHAVIORS)
            and case["comparison"]["behavior_gate_passed"]
            for case in cases
        ),
        "ratchet_failures": sum(bool(case["ratchet_errors"]) for case in cases),
        "performance_warnings": sum(bool(case["ratchet_warnings"]) for case in cases),
        "profile": profile,
        "shard": f"{shard[0]}/{shard[1]}",
    }
    # Capture provenance after every runner-owned artifact except report.json
    # has been written.  When output_root is inside the checkout those files
    # are the one ignored subtree; unrelated changes remain visible.
    _write_junit(cases, output_root / "junit.xml")
    repository_end = _repository_snapshot(output_root)
    implementation_commit, implementation_dirty = _implementation_provenance(
        repository_start,
        repository_end,
    )
    report = {
        "schema_version": 2,
        "harness_version": HARNESS_VERSION,
        "implementation_commit": implementation_commit,
        "implementation_dirty": implementation_dirty,
        "python_interpreter": python_interpreter,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "extended_spec_sha256": hashlib.sha256(extended_spec_path.read_bytes()).hexdigest(),
        "environment_profile": profile,
        "matplotlib_version": manifest["matplotlib_version"],
        "summary": summary,
        "examples": cases,
    }
    (output_root / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--profile", choices=("standard", "extended", "all"), default="standard")
    parser.add_argument("--shard", type=_parse_shard, default=(0, 1))
    parser.add_argument("--match")
    parser.add_argument("--engine", choices=("both", "matplotlib", "xy"), default="both")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse terminal per-case results already present below --output",
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    parser.add_argument("--corpus-root", type=Path, default=CORPUS_ROOT)
    parser.add_argument(
        "--extended-spec",
        type=Path,
        default=EXTENDED_SPEC_PATH,
        help="dependency/backend/driver contract for extended examples",
    )
    args = parser.parse_args()
    engines = ("matplotlib", "xy") if args.engine == "both" else (args.engine,)
    report = run_gallery(
        output_root=args.output,
        python=args.python,
        timeout=args.timeout,
        workers=args.workers,
        profile=args.profile,
        shard=args.shard,
        match=args.match,
        engines=engines,
        resume=args.resume,
        manifest_path=args.manifest,
        baseline_path=args.baseline,
        corpus_root=args.corpus_root,
        extended_spec_path=args.extended_spec,
    )
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 1 if report["summary"]["ratchet_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main())
