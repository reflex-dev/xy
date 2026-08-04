"""Build and verify the immutable Matplotlib 3.11 gallery contract."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import inspect
import json
import re
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from . import HARNESS_VERSION
from .behavior import behavior_gate
from .integrity import capture_integrity_errors
from .provenance import valid_python_interpreter
from .rewrite import pyplot_imports, rewrite_pyplot_imports

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = REPO_ROOT / "gallery" / "matplotlib-3.11.1"
EXAMPLES_ROOT = CORPUS_ROOT / "examples"
MANIFEST_PATH = CORPUS_ROOT / "manifest.json"
BASELINE_PATH = CORPUS_ROOT / "baseline.json"
PROVENANCE_PATH = CORPUS_ROOT / "provenance.json"
EXTENDED_SPEC_PATH = CORPUS_ROOT / "extended-environment.json"
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GALLERY_DOCUMENTATION_VERSION = "3.11.1"
COMPATIBILITY_ORACLE_VERSION = "3.11.0"
GALLERY_SNAPSHOT_DOWNLOADED_ON = "2026-07-30"
ARCHIVE_SOURCE_COUNT = 507
EXCLUDED_3D_SOURCE_COUNT = 48
CONTRACT_SOURCE_COUNT = ARCHIVE_SOURCE_COUNT - EXCLUDED_3D_SOURCE_COUNT
PYPLOT_ELIGIBLE_COUNT = 437
EXPECTED_PROFILE_COUNTS = {"extended": 12, "non_pyplot": 22, "standard": 425}
# Independently pinned from the initial d505ef... audit after removing the 48
# examples outside XY's two-dimensional contract.  The verifier must not
# derive this oracle from the mutable schema-1 baseline it is checking.
LEGACY_SCHEMA_ONE_AUDIT_COMMIT = "d505ef5789d8b18e23fd838300b039932dc399ce"
LEGACY_SCHEMA_ONE_SUMMARY = {
    "source_count": CONTRACT_SOURCE_COUNT,
    "pyplot_eligible_count": PYPLOT_ELIGIBLE_COUNT,
    "standard_profile_count": EXPECTED_PROFILE_COUNTS["standard"],
    "extended_profile_count": EXPECTED_PROFILE_COUNTS["extended"],
    "xy_execution_passed": 189,
    "capture_parity_passed": 172,
    "dimension_parity_passed": 168,
    "visual_gate_passed": 127,
    "temporary_waiver_count": 327,
}

EXPECTED_ARCHIVES = {
    "python": {
        "filename": "gallery_python.zip",
        "sha256": "fcbf2359353c06443e7f6c5477acb82e7bbf9d79672bd2c1e597ff5e357248bc",
        "url": (
            "https://matplotlib.org/stable/_downloads/"
            "46b4cb42d5bb56cc39e2b5b2b520b38d/gallery_python.zip"
        ),
    },
    "jupyter": {
        "filename": "gallery_jupyter.zip",
        "sha256": "bb00657280bf0dfaac11ccf56bff15e959b90ba8d0365e055e9f4ef971edf870",
        "url": (
            "https://matplotlib.org/stable/_downloads/"
            "fcaddee3a42ae2e2c41e00ae08d70347/gallery_jupyter.zip"
        ),
    },
}

KNOWN_ISSUES = {
    "images_contours_and_fields/matshow.py": {
        "number": 411,
        "url": "https://github.com/reflex-dev/xy/issues/411",
    },
    "lines_bars_and_markers/scatter_hist.py": {
        "number": 354,
        "url": "https://github.com/reflex-dev/xy/issues/354",
    },
    "text_labels_and_annotations/angles_on_bracket_arrows.py": {
        "number": 409,
        "url": "https://github.com/reflex-dev/xy/issues/409",
    },
    "text_labels_and_annotations/dfrac_demo.py": {
        "number": 410,
        "url": "https://github.com/reflex-dev/xy/issues/410",
    },
}

ALLOWED_GALLERY_ADAPTERS: dict[str, dict[str, list[dict[str, Any]]]] = {
    "event_handling/resample.py": {
        "matplotlib": [
            {
                "artist_type": "matplotlib.collections.FillBetweenPolyCollection",
                "figure_index": 0,
                "id": "matplotlib-3.11-fill-between-set-data-step",
            }
        ],
        "xy": [],
    }
}

RASTER_MESH_CALLS = {
    "imshow",
    "matshow",
    "pcolor",
    "pcolormesh",
    "pcolorfast",
    "tripcolor",
    "specgram",
}
FILLED_VECTOR_CALLS = {
    "bar",
    "barh",
    "boxplot",
    "broken_barh",
    "contourf",
    "errorbar",
    "eventplot",
    "fill",
    "fill_between",
    "fill_betweenx",
    "hexbin",
    "hist",
    "hist2d",
    "pie",
    "quiver",
    "scatter",
    "stackplot",
    "streamplot",
    "violinplot",
}
INTERACTION_CALLS = {
    "add_callback",
    "button_press_event",
    "connect",
    "disconnect",
    "draggable",
    "ginput",
    "mpl_connect",
    "mpl_disconnect",
    "new_timer",
    "pause",
    "pick",
    "set_active",
    "set_draggable",
    "start_event_loop",
    "waitforbuttonpress",
}
INTERACTION_IMPORTS = {
    "matplotlib.animation",
    "matplotlib.backend_bases",
    "matplotlib.widgets",
}
EXAMPLE_BEHAVIOR_OVERRIDES = {
    "images_contours_and_fields/colormap_interactive_adjustment.py": (
        "interactive",
        "navigation",
    ),
    "misc/hyperlinks_sgskip.py": ("interactive",),
    "showcase/pan_zoom_overlap.py": ("interactive", "navigation"),
    "subplots_axes_and_figures/shared_axis_demo.py": ("interactive", "navigation"),
    "text_labels_and_annotations/angle_annotation.py": ("interactive", "navigation"),
    "ticks/major_minor_demo.py": ("interactive", "navigation"),
    "user_interfaces/svg_histogram_sgskip.py": ("interactive",),
    "user_interfaces/svg_tooltip_sgskip.py": ("interactive",),
    "widgets/mouse_cursor.py": ("interactive", "cursor"),
}


def _is_excluded_3d_example(path: str) -> bool:
    """Return whether an upstream archive member is outside XY's 2-D contract."""

    return path.startswith("mplot3d/") or path == "animation/random_walk.py"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _ast_dump_show_empty_fallback(value: object) -> str:
    """Match ``ast.dump(..., show_empty=True)`` on older interpreters.

    Python 3.11 also predates the empty ``type_params`` fields added to
    function and class definitions in Python 3.12.  Gallery sources use the
    Python 3.11 grammar, so synthesizing those empty fields gives every
    supported interpreter the same canonical AST schema.
    """

    if isinstance(value, ast.AST):
        fields = list(value._fields)
        if (
            isinstance(value, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and "type_params" not in fields
        ):
            fields.append("type_params")

        rendered_fields: list[str] = []
        for name in fields:
            if name == "type_params" and not hasattr(value, name):
                field_value: object = []
            else:
                try:
                    field_value = getattr(value, name)
                except AttributeError:
                    continue
            if field_value is None and getattr(type(value), name, ...) is None:
                continue
            rendered_fields.append(f"{name}={_ast_dump_show_empty_fallback(field_value)}")
        return f"{type(value).__name__}({', '.join(rendered_fields)})"
    if isinstance(value, list):
        return f"[{', '.join(_ast_dump_show_empty_fallback(item) for item in value)}]"
    return repr(value)


class _CanonicalAstTransformer(ast.NodeTransformer):
    """Remove parser-version artifacts that do not affect Python semantics."""

    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.JoinedStr:  # noqa: N802
        self.generic_visit(node)
        # CPython 3.12.0-3.12.3 retained a redundant empty literal at the end
        # of some dynamic f-string format specifications.  Later 3.12 patch
        # releases, 3.11, and 3.13+ omit it.  Empty literals have no runtime
        # effect, so exclude them from the immutable source/notebook contract.
        node.values = [
            value
            for value in node.values
            if not (isinstance(value, ast.Constant) and value.value == "")
        ]
        return node


def _canonical_ast(tree: ast.AST) -> ast.AST:
    """Return a canonical AST without mutating the caller's parsed tree."""

    return _CanonicalAstTransformer().visit(copy.deepcopy(tree))


def _stable_ast_dump(tree: ast.AST) -> str:
    """Serialize an AST identically on supported CPython versions."""

    tree = _canonical_ast(tree)
    if "show_empty" in inspect.signature(ast.dump).parameters:
        kwargs: dict[str, Any] = {"include_attributes": False, "show_empty": True}
        return ast.dump(tree, **kwargs)
    return _ast_dump_show_empty_fallback(tree)


def _normalized_script_ast(source: str, filename: str) -> str:
    tree = ast.parse(source, filename=filename)
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        tree.body.pop(0)
    return _stable_ast_dump(tree)


def _notebook_code(notebook: dict[str, Any]) -> str:
    return "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
    )


def _call_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def _import_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _has_coordinate_behavior(tree: ast.AST) -> bool:
    coordinate_attributes = {"fmt_xdata", "fmt_ydata", "format_coord"}
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "format_coord"
        ):
            return True
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(
            isinstance(target, ast.Attribute) and target.attr in coordinate_attributes
            for target in targets
        ):
            return True
    return False


def _classify_source(tree: ast.AST, path: str | None = None) -> tuple[str, list[str]]:
    calls = _call_names(tree)
    imports = _import_names(tree)
    if calls & RASTER_MESH_CALLS:
        render_class = "raster_mesh"
    elif calls & FILLED_VECTOR_CALLS:
        render_class = "filled_vector"
    else:
        render_class = "text_thin_line"

    behavior: list[str] = []
    if calls & INTERACTION_CALLS or imports & INTERACTION_IMPORTS:
        behavior.append("interactive")
    if (
        "pause" in calls
        or "matplotlib.animation" in imports
        or any(name.endswith("Animation") for name in calls)
    ):
        behavior.append("animation")
    if _has_coordinate_behavior(tree):
        if "interactive" not in behavior:
            behavior.append("interactive")
        behavior.append("coordinates")
    if any(
        name.startswith(("mpl_toolkits.axes_grid1", "mpl_toolkits.axisartist")) for name in imports
    ):
        behavior.append("toolkit")
    for requirement in EXAMPLE_BEHAVIOR_OVERRIDES.get(path or "", ()):
        if requirement not in behavior:
            behavior.append(requirement)
    if not behavior:
        behavior.append("static")
    return render_class, behavior


def _dimension_policy(tree: ast.AST) -> str:
    """Classify the strongest canvas-size rule visible in the example."""

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        else:
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
        if name == "savefig":
            value = keywords.get("bbox_inches")
            if isinstance(value, ast.Constant) and value.value == "tight":
                return "tight"
        if name in {"figure", "subplots", "subplot_mosaic"} and "figsize" in keywords:
            return "explicit"
    return "default"


def _environment_requirement(path: str, result: dict[str, Any]) -> str:
    text = " ".join(
        [
            path,
            str(result.get("exception_type", "")),
            str(result.get("exception_message", "")),
        ]
    ).lower()
    if "latex" in text or "tex_demo" in text or "usetex" in text:
        return "tex"
    if "colorspacious" in text:
        return "optional_dependency"
    if "gtk" in text or "backend" in text or "toolmanager" in text:
        return "gui_backend"
    if "multiprocess" in text or "pickl" in text:
        return "multiprocessing"
    if result.get("status") == "timeout" or "ginput" in text:
        return "interactive_input"
    if result.get("exception_type") == "SystemExit":
        return "command_line_arguments"
    return "extended_environment"


def _safe_members(archive: zipfile.ZipFile, suffix: str) -> dict[str, zipfile.ZipInfo]:
    members: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        if info.is_dir() or not info.filename.endswith(suffix):
            continue
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe archive member: {info.filename}")
        if info.filename in members:
            raise ValueError(f"duplicate archive member: {info.filename}")
        members[info.filename] = info
    return members


def _load_audit(path: Path) -> dict[str, dict[str, Any]]:
    audit = json.loads(path.read_text(encoding="utf-8"))
    examples = audit.get("examples")
    if not isinstance(examples, list):
        raise ValueError("audit summary must contain an examples list")
    return {str(example["relative_source"]): example for example in examples}


def _clean_destination_sources(
    examples_root: Path,
    *,
    archive_paths: set[str],
    included_paths: set[str],
) -> None:
    """Remove only excluded archive members from an existing destination."""

    existing = {path.relative_to(examples_root).as_posix() for path in examples_root.rglob("*.py")}
    unexpected = existing - archive_paths
    if unexpected:
        raise ValueError(
            "destination contains sources outside the archive: "
            + ", ".join(sorted(unexpected)[:10])
        )
    excluded_archive_paths = archive_paths - included_paths
    for path in sorted(existing & excluded_archive_paths):
        examples_root.joinpath(*PurePosixPath(path).parts).unlink()


def _baseline_entry(
    path: str,
    eligible: bool,
    audit: dict[str, Any],
    *,
    audit_root: Path,
    render_class: str,
) -> dict[str, Any]:
    reference = audit["matplotlib"]
    xy_result = audit["xy"]
    both_passed = reference.get("status") == "passed" and xy_result.get("status") == "passed"
    capture_parity = bool(
        both_passed
        and reference.get("capture_count", 0) > 0
        and reference.get("capture_count") == xy_result.get("capture_count")
    )
    dimension_parity = bool(
        capture_parity
        and len(audit.get("figure_pairs", [])) == reference.get("capture_count")
        and all(pair.get("dimensions_match") for pair in audit.get("figure_pairs", []))
    )
    visual_gate_passed: bool | None = None
    visual_decisions: list[str] = []
    if capture_parity:
        from .metrics import compare_images, evaluate_visual

        slug = "__".join(PurePosixPath(path).with_suffix("").parts)
        visual_gate_passed = True
        for index, _pair in enumerate(audit.get("figure_pairs", [])):
            try:
                reference_capture = reference["captures"][index]["file"]
                xy_capture = xy_result["captures"][index]["file"]
                metrics = compare_images(
                    audit_root / slug / "matplotlib" / reference_capture,
                    audit_root / slug / "xy" / xy_capture,
                )
                decision = evaluate_visual(metrics, render_class).decision
            except (IndexError, KeyError, OSError, ValueError):
                decision = "unavailable"
            visual_decisions.append(decision)
            visual_gate_passed &= decision == "pass"

    waivers: list[dict[str, Any]] = []
    if eligible:
        if reference.get("status") != "passed":
            waivers.append(
                {
                    "id": "reference-environment",
                    "temporary": True,
                    "reason": _environment_requirement(path, reference),
                }
            )
        if xy_result.get("status") != "passed":
            waivers.append(
                {
                    "id": "xy-execution",
                    "temporary": True,
                    "reason": str(xy_result.get("exception_type") or xy_result.get("status")),
                }
            )
        elif not capture_parity:
            waivers.append(
                {
                    "id": "capture-structure",
                    "temporary": True,
                    "reason": (
                        f"reference={reference.get('capture_count', 0)}, "
                        f"xy={xy_result.get('capture_count', 0)}"
                    ),
                }
            )
        elif not dimension_parity:
            waivers.append(
                {
                    "id": "canvas-dimensions",
                    "temporary": True,
                    "reason": "one or more paired canvases differ in dimensions",
                }
            )
        if capture_parity and visual_gate_passed is not True:
            issue = KNOWN_ISSUES.get(path)
            waivers.append(
                {
                    "id": (
                        f"visual-issue-{issue['number']}" if issue is not None else "visual-format"
                    ),
                    "temporary": True,
                    "reason": f"visual decisions: {visual_decisions}",
                }
            )

    return {
        "reference": {
            "status": reference.get("status"),
            "capture_count": int(reference.get("capture_count", 0)),
            "duration_seconds": float(reference.get("duration_seconds", 0.0)),
        },
        "xy": {
            "status": xy_result.get("status"),
            "capture_count": int(xy_result.get("capture_count", 0)),
            "duration_seconds": float(xy_result.get("duration_seconds", 0.0)),
        },
        "capture_parity": capture_parity,
        "dimension_parity": dimension_parity,
        "visual_gate_passed": visual_gate_passed,
        "visual_decisions": visual_decisions,
        "temporary_waivers": waivers,
    }


def _legacy_summary(
    *,
    manifest: dict[str, Any],
    baseline_examples: dict[str, dict[str, Any]],
) -> dict[str, int]:
    """Summarize a schema-1 audit after applying the contract path filter."""

    eligible = [
        baseline_examples[entry["path"]]
        for entry in manifest["examples"]
        if entry["pyplot_eligible"]
    ]
    return {
        "source_count": int(manifest["source_count"]),
        "pyplot_eligible_count": len(eligible),
        "standard_profile_count": int(manifest["profile_counts"]["standard"]),
        "extended_profile_count": int(manifest["profile_counts"]["extended"]),
        "xy_execution_passed": sum(entry["xy"]["status"] == "passed" for entry in eligible),
        "capture_parity_passed": sum(bool(entry["capture_parity"]) for entry in eligible),
        "dimension_parity_passed": sum(bool(entry["dimension_parity"]) for entry in eligible),
        "visual_gate_passed": sum(entry["visual_gate_passed"] is True for entry in eligible),
        "temporary_waiver_count": sum(len(entry["temporary_waivers"]) for entry in eligible),
    }


def build_contract(
    *,
    python_archive: Path,
    notebook_archive: Path,
    audit_summary: Path,
    destination: Path = CORPUS_ROOT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract exact sources and generate the AST manifest and ratchet baseline."""

    archives = {"python": python_archive, "jupyter": notebook_archive}
    for kind, path in archives.items():
        digest = _sha256(path.read_bytes())
        expected = EXPECTED_ARCHIVES[kind]["sha256"]
        if digest != expected:
            raise ValueError(f"{kind} archive sha256 {digest} != expected {expected}")

    audit_by_path = _load_audit(audit_summary)
    examples_root = destination / "examples"
    examples_root.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    baseline_entries: dict[str, Any] = {}
    with (
        zipfile.ZipFile(python_archive) as python_zip,
        zipfile.ZipFile(notebook_archive) as notebook_zip,
    ):
        python_members = _safe_members(python_zip, ".py")
        notebook_members = _safe_members(notebook_zip, ".ipynb")
        if (
            len(python_members) != ARCHIVE_SOURCE_COUNT
            or len(notebook_members) != ARCHIVE_SOURCE_COUNT
        ):
            raise ValueError(
                f"expected {ARCHIVE_SOURCE_COUNT} sources and notebooks, got "
                f"{len(python_members)} and {len(notebook_members)}"
            )

        expected_notebooks = {
            str(PurePosixPath(path).with_suffix(".ipynb")) for path in python_members
        }
        if expected_notebooks != set(notebook_members):
            raise ValueError("Python and notebook archive paths do not map one-to-one")
        if set(python_members) != set(audit_by_path):
            raise ValueError("audit paths do not exactly match the Python archive")
        included_members = {
            path: member
            for path, member in python_members.items()
            if not _is_excluded_3d_example(path)
        }
        if len(included_members) != CONTRACT_SOURCE_COUNT:
            raise ValueError(
                f"expected {CONTRACT_SOURCE_COUNT} non-3-D sources, got {len(included_members)}"
            )
        _clean_destination_sources(
            examples_root,
            archive_paths=set(python_members),
            included_paths=set(included_members),
        )

        for path in sorted(included_members):
            source_bytes = python_zip.read(included_members[path])
            source = source_bytes.decode("utf-8")
            notebook_path = str(PurePosixPath(path).with_suffix(".ipynb"))
            notebook_bytes = notebook_zip.read(notebook_members[notebook_path])
            notebook = json.loads(notebook_bytes)

            script_ast = _normalized_script_ast(source, path)
            notebook_ast = _stable_ast_dump(
                ast.parse(_notebook_code(notebook), filename=notebook_path)
            )
            if script_ast != notebook_ast:
                raise ValueError(f"notebook code AST differs from Python source: {path}")

            output = examples_root.joinpath(*PurePosixPath(path).parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(source_bytes)

            tree = ast.parse(source, filename=path)
            imports = pyplot_imports(tree)
            eligible = bool(imports)
            audit = audit_by_path[path]
            reference = audit["matplotlib"]
            if not eligible:
                profile = "non_pyplot"
                expected_reference = "not_a_pyplot_replacement"
                requirement = None
            elif reference.get("status") == "passed":
                profile = "standard"
                expected_reference = "pass"
                requirement = None
            else:
                profile = "extended"
                expected_reference = "pass_with_extended_environment"
                requirement = _environment_requirement(path, reference)

            render_class, behavior = _classify_source(tree, path)
            baseline_entry = _baseline_entry(
                path,
                eligible,
                audit,
                audit_root=audit_summary.parent,
                render_class=render_class,
            )
            baseline_entries[path] = baseline_entry
            entries.append(
                {
                    "path": path,
                    "sha256": _sha256(source_bytes),
                    "byte_count": len(source_bytes),
                    "notebook_path": notebook_path,
                    "notebook_sha256": _sha256(notebook_bytes),
                    "normalized_ast_sha256": _sha256(script_ast.encode()),
                    "notebook_code_ast_sha256": _sha256(notebook_ast.encode()),
                    "notebook_ast_matches": True,
                    "pyplot_eligible": eligible,
                    "pyplot_imports": imports,
                    "profile": profile,
                    "extended_environment": requirement,
                    "expected_reference_result": expected_reference,
                    "render_class": render_class,
                    "dimension_policy": _dimension_policy(tree),
                    "behavior": behavior,
                    "issue": KNOWN_ISSUES.get(path),
                    "temporary_waivers": baseline_entry["temporary_waivers"],
                }
            )

    profile_counts = Counter(entry["profile"] for entry in entries)
    manifest = {
        "schema_version": 1,
        "matplotlib_version": COMPATIBILITY_ORACLE_VERSION,
        "gallery_documentation_version": GALLERY_DOCUMENTATION_VERSION,
        "gallery_snapshot_downloaded_on": GALLERY_SNAPSHOT_DOWNLOADED_ON,
        "source_count": len(entries),
        "notebook_count": len(entries),
        "pyplot_eligible_count": sum(entry["pyplot_eligible"] for entry in entries),
        "profile_counts": dict(sorted(profile_counts.items())),
        "archives": {
            kind: {
                **EXPECTED_ARCHIVES[kind],
                "member_count": ARCHIVE_SOURCE_COUNT,
            }
            for kind in ("python", "jupyter")
        },
        "gallery_adapters": ALLOWED_GALLERY_ADAPTERS,
        "examples": entries,
    }

    baseline = {
        "schema_version": 1,
        "audit_commit": LEGACY_SCHEMA_ONE_AUDIT_COMMIT,
        "matplotlib_version": "3.11.0",
        "summary": _legacy_summary(
            manifest=manifest,
            baseline_examples=baseline_entries,
        ),
        "examples": baseline_entries,
    }

    destination.mkdir(parents=True, exist_ok=True)
    (destination / "manifest.json").write_bytes(_json_bytes(manifest))
    (destination / "baseline.json").write_bytes(_json_bytes(baseline))
    from .extended_environment import write_spec

    write_spec(destination)
    return manifest, baseline


def _waiver_keys(entry: dict[str, Any]) -> set[str]:
    return {str(waiver["id"]) for waiver in entry.get("temporary_waivers", [])}


def _accepted_report_case(
    case: dict[str, Any],
    *,
    expected_behavior: list[str] | tuple[str, ...] = (),
) -> list[str]:
    """Return hard acceptance failures for one differential report case."""

    path = str(case.get("path", "<unknown>"))
    errors: list[str] = []
    engines = case.get("engines", {})
    if not isinstance(engines, dict):
        return [f"{path}: engine results are missing or invalid"]
    capture_counts: dict[str, int] = {}
    for engine in ("matplotlib", "xy"):
        result = engines.get(engine, {})
        if result.get("status") != "passed":
            errors.append(f"{path}: {engine} did not complete")
        errors.extend(
            f"{path}: {engine} {reason}" for reason in capture_integrity_errors(engine, result)
        )
        captures = result.get("captures")
        capture_count = result.get("capture_count")
        if not isinstance(capture_count, int) or isinstance(capture_count, bool):
            errors.append(f"{path}: {engine} capture_count is missing or invalid")
        elif not isinstance(captures, list) or capture_count != len(captures):
            errors.append(
                f"{path}: {engine} capture_count {capture_count!r} "
                f"does not match {len(captures) if isinstance(captures, list) else 'invalid'} captures"
            )
        else:
            capture_counts[engine] = capture_count
        if expected_behavior:
            behavior_passed, behavior_reasons = behavior_gate(result, expected_behavior)
            if not behavior_passed:
                errors.append(
                    f"{path}: {engine} behavior evidence did not pass: "
                    + "; ".join(behavior_reasons)
                )

    if (
        set(capture_counts) == {"matplotlib", "xy"}
        and capture_counts["matplotlib"] != capture_counts["xy"]
    ):
        errors.append(
            f"{path}: reference/xy capture counts differ "
            f"({capture_counts['matplotlib']} != {capture_counts['xy']})"
        )

    comparison = case.get("comparison", {})
    if not isinstance(comparison, dict):
        return [*errors, f"{path}: comparison metadata is missing or invalid"]
    for field in (
        "capture_parity",
        "dimension_gate_passed",
        "visual_gate_passed",
        "semantic_gate_passed",
        "behavior_gate_passed",
    ):
        if comparison.get(field) is not True:
            errors.append(f"{path}: {field} did not pass")
    figure_pairs = comparison.get("figure_pairs")
    expected_pairs = capture_counts.get("matplotlib")
    if (
        not isinstance(figure_pairs, list)
        or expected_pairs is None
        or len(figure_pairs) != expected_pairs
    ):
        errors.append(
            f"{path}: figure_pairs must contain one entry per capture "
            f"(expected {expected_pairs}, got "
            f"{len(figure_pairs) if isinstance(figure_pairs, list) else 'invalid'})"
        )
    else:
        for index, pair in enumerate(figure_pairs):
            if not isinstance(pair, dict):
                errors.append(f"{path}: figure pair {index} is invalid")
                continue
            dimension_gate = pair.get("dimension_gate")
            if not isinstance(dimension_gate, dict) or dimension_gate.get("decision") != "pass":
                errors.append(f"{path}: figure pair {index} dimension gate detail did not pass")
            visual_gate = pair.get("visual_gate")
            if not isinstance(visual_gate, dict) or visual_gate.get("decision") != "pass":
                errors.append(f"{path}: figure pair {index} visual gate detail did not pass")
            if pair.get("semantic_differences") != []:
                errors.append(f"{path}: figure pair {index} has semantic differences")
            if not isinstance(pair.get("metrics"), dict):
                errors.append(f"{path}: figure pair {index} visual metrics are missing")
    if case.get("temporary_waivers"):
        errors.append(f"{path}: temporary waivers remain")
    if case.get("ratchet_errors"):
        errors.append(f"{path}: ratchet errors remain")
    return errors


def _accepted_baseline_entry(entry: dict[str, Any]) -> bool:
    return bool(
        entry.get("reference", {}).get("status") == "passed"
        and entry.get("xy", {}).get("status") == "passed"
        and entry.get("capture_parity")
        and entry.get("dimension_gate_passed")
        and entry.get("visual_gate_passed")
        and entry.get("semantic_gate_passed")
        and entry.get("behavior_gate_passed")
        and not entry.get("temporary_waivers")
    )


def _promoted_summary(
    *,
    manifest: dict[str, Any],
    baseline_examples: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    eligible = [
        baseline_examples[entry["path"]]
        for entry in manifest["examples"]
        if entry["pyplot_eligible"]
    ]
    accepted = sum(_accepted_baseline_entry(entry) for entry in eligible)
    return {
        "source_count": manifest["source_count"],
        "pyplot_eligible_count": len(eligible),
        "standard_profile_count": manifest["profile_counts"]["standard"],
        "extended_profile_count": manifest["profile_counts"]["extended"],
        "xy_execution_passed": sum(
            entry.get("xy", {}).get("status") == "passed" for entry in eligible
        ),
        "capture_parity_passed": sum(bool(entry.get("capture_parity")) for entry in eligible),
        "dimension_parity_passed": sum(
            bool(entry.get("dimension_gate_passed")) for entry in eligible
        ),
        "exact_dimension_parity_passed": sum(
            bool(entry.get("exact_dimension_parity")) for entry in eligible
        ),
        "visual_gate_passed": sum(entry.get("visual_gate_passed") is True for entry in eligible),
        "semantic_gate_passed": sum(
            entry.get("semantic_gate_passed") is True for entry in eligible
        ),
        "behavior_gate_passed": sum(
            entry.get("behavior_gate_passed") is True for entry in eligible
        ),
        "accepted_examples": accepted,
        "temporary_waiver_count": sum(
            len(entry.get("temporary_waivers", [])) for entry in eligible
        ),
        "acceptance_complete": accepted == len(eligible),
    }


def _case_provenance_errors(
    *,
    case: dict[str, Any],
    entry: dict[str, Any],
    root: Path,
    extended_requirements: dict[str, Any] | None,
    python_interpreter: dict[str, str],
) -> list[str]:
    """Verify that a report case came from the current exact-source harness."""

    path = str(entry["path"])
    errors: list[str] = []
    for field in ("profile", "render_class", "behavior"):
        if case.get(field) != entry.get(field):
            errors.append(f"{path}: report {field} differs from the manifest")
    if case.get("extended_environment") != extended_requirements:
        errors.append(f"{path}: report extended environment differs from the contract")

    source_bytes = (root / "examples" / path).read_bytes()
    source_sha256 = _sha256(source_bytes)
    rewritten = rewrite_pyplot_imports(source_bytes.decode("utf-8"), filename=path)
    transformed_sha256 = _sha256(rewritten.source.encode("utf-8"))
    engines = case.get("engines")
    if not isinstance(engines, dict):
        return [*errors, f"{path}: engine results are missing or invalid"]

    expected_backends = (
        extended_requirements.get("backends", {})
        if isinstance(extended_requirements, dict)
        else {"matplotlib": "Agg", "xy": "Agg"}
    )
    for engine in ("matplotlib", "xy"):
        result = engines.get(engine)
        if not isinstance(result, dict):
            errors.append(f"{path}: {engine} result is missing or invalid")
            continue
        expected_mode = "compat" if engine == "xy" else None
        expected_rewrite_count = rewritten.import_count if engine == "xy" else 0
        expected_transformed = transformed_sha256 if engine == "xy" else source_sha256
        expected_backend = expected_backends.get(engine)
        checks = {
            "schema_version": 2,
            "harness_version": HARNESS_VERSION,
            "engine": engine,
            "source_sha256": source_sha256,
            "transformed_sha256": expected_transformed,
            "rewrite_count": expected_rewrite_count,
            "ast_rewrite_verified": True,
            "python_interpreter": python_interpreter,
            "requested_pyplot_mode": expected_mode,
            "resolved_pyplot_mode": expected_mode,
            "requested_matplotlib_backend": expected_backend,
            "behavior_requirements": entry.get("behavior", []),
            "extended_requirements": extended_requirements,
        }
        for field, expected in checks.items():
            if result.get(field) != expected:
                errors.append(
                    f"{path}: {engine} {field} {result.get(field)!r} does not match {expected!r}"
                )
        behavior = result.get("behavior")
        adapters = behavior.get("gallery_adapters") if isinstance(behavior, dict) else None
        expected_adapters = ALLOWED_GALLERY_ADAPTERS.get(path, {}).get(engine, [])
        if adapters != expected_adapters:
            errors.append(
                f"{path}: {engine} gallery adapters {adapters!r} "
                f"do not match the explicit allowlist {expected_adapters!r}"
            )
    return errors


def promote_reports(
    reports: list[Path],
    *,
    audit_commit: str,
    root: Path = CORPUS_ROOT,
    verify_repository: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Promote fully accepted report cases into the monotonic baseline.

    Promotion is fail-closed and all-or-nothing: every supplied case must pass
    execution, fallback, capture, dimension, semantic, behavior, visual, and
    performance-ratchet gates before any checked-in contract file is written.
    """

    if not reports:
        raise ValueError("at least one report is required")
    if COMMIT_SHA_PATTERN.fullmatch(audit_commit) is None:
        raise ValueError("audit_commit must be a lowercase 40-character Git commit SHA")
    if verify_repository:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        current_head = completed.stdout.strip() if completed.returncode == 0 else None
        if current_head != audit_commit:
            raise ValueError(
                f"audit_commit {audit_commit!r} does not match repository HEAD {current_head!r}"
            )
    manifest_path = root / "manifest.json"
    baseline_path = root / "baseline.json"
    extended_spec_path = root / "extended-environment.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    manifest_by_path = {entry["path"]: entry for entry in manifest["examples"]}
    from .extended_environment import load_spec, validate_complete_report

    extended_spec = load_spec(extended_spec_path)
    extended_by_path = {str(entry["path"]): entry for entry in extended_spec.get("examples", [])}
    cases_by_path: dict[str, dict[str, Any]] = {}
    report_records: list[dict[str, Any]] = []
    report_profiles: set[str] = set()
    errors: list[str] = []
    # Reports identify the exact manifest bytes they consumed.  Promotion
    # canonicalizes that manifest when it writes the checked-in contract, so
    # keep the input digest separate from the digest of the emitted bytes.
    # Conflating the two makes an otherwise valid promotion immediately fail
    # schema-3 verification whenever the input JSON was not already canonical.
    report_manifest_sha256 = _sha256(manifest_path.read_bytes())
    extended_spec_sha256 = _sha256(extended_spec_path.read_bytes())

    for report_path in reports:
        report_bytes = report_path.read_bytes()
        report = json.loads(report_bytes)
        profile = report.get("environment_profile")
        raw_python_interpreter = report.get("python_interpreter")
        if valid_python_interpreter(raw_python_interpreter):
            python_interpreter = dict(raw_python_interpreter)
        else:
            errors.append(f"{report_path}: python_interpreter is missing or invalid")
            python_interpreter = {}
        if profile not in {"standard", "extended"}:
            errors.append(f"{report_path}: environment profile is missing or invalid")
        else:
            report_profiles.add(profile)
        for field, expected in (
            ("schema_version", 2),
            ("harness_version", HARNESS_VERSION),
            ("implementation_commit", audit_commit),
            ("implementation_dirty", False),
            ("manifest_sha256", report_manifest_sha256),
            ("extended_spec_sha256", extended_spec_sha256),
        ):
            if report.get(field) != expected:
                errors.append(
                    f"{report_path}: {field} {report.get(field)!r} does not match {expected!r}"
                )
        if report.get("summary", {}).get("profile") != profile:
            errors.append(f"{report_path}: summary profile differs from report provenance")
        if report.get("matplotlib_version") != manifest.get("matplotlib_version"):
            errors.append(
                f"{report_path}: Matplotlib version "
                f"{report.get('matplotlib_version')!r} does not match "
                f"{manifest.get('matplotlib_version')!r}"
            )
        report_records.append(
            {
                "profile": profile,
                "sha256": _sha256(report_bytes),
                "harness_version": report.get("harness_version"),
                "python_interpreter": python_interpreter,
                "implementation_commit": report.get("implementation_commit"),
                "report_manifest_sha256": report.get("manifest_sha256"),
                "extended_spec_sha256": report.get("extended_spec_sha256"),
            }
        )
        for case in report.get("examples", []):
            path = str(case.get("path"))
            if path in cases_by_path:
                errors.append(f"{path}: appears in more than one promotion report")
                continue
            entry = manifest_by_path.get(path)
            if entry is None:
                errors.append(f"{path}: is not present in the gallery manifest")
                continue
            if not entry.get("pyplot_eligible"):
                errors.append(f"{path}: is not a pyplot-replacement example")
                continue
            if entry.get("profile") != profile:
                errors.append(
                    f"{path}: manifest profile {entry.get('profile')!r} "
                    f"does not match report profile {profile!r}"
                )
                continue
            cases_by_path[path] = case
            expected_extended = extended_by_path.get(path)
            errors.extend(
                _case_provenance_errors(
                    case=case,
                    entry=entry,
                    root=root,
                    extended_requirements=expected_extended,
                    python_interpreter=python_interpreter,
                )
            )
            errors.extend(
                _accepted_report_case(
                    case,
                    expected_behavior=entry.get("behavior", []),
                )
            )
        if profile == "extended":
            errors.extend(
                f"{report_path}: {error}"
                for error in validate_complete_report(report, spec=extended_spec)
            )

    eligible_paths = {
        path for path, entry in manifest_by_path.items() if entry.get("pyplot_eligible")
    }
    expected_profiles = {
        str(entry["profile"]) for entry in manifest_by_path.values() if entry.get("pyplot_eligible")
    }
    if report_profiles != expected_profiles:
        errors.append(
            "promotion requires one report for every eligible profile: "
            f"expected {sorted(expected_profiles)}, got {sorted(report_profiles)}"
        )
    if set(cases_by_path) != eligible_paths:
        errors.append(
            "promotion reports must cover every pyplot-eligible example: "
            f"missing={sorted(eligible_paths - set(cases_by_path))}, "
            f"unexpected={sorted(set(cases_by_path) - eligible_paths)}"
        )
    if errors:
        raise ValueError("\n".join(errors))

    baseline_examples = baseline["examples"]
    for path, case in cases_by_path.items():
        engines = case["engines"]
        comparison = case["comparison"]

        def result_record(
            engine: str,
            engine_results: dict[str, dict[str, Any]] = engines,
        ) -> dict[str, Any]:
            result = engine_results[engine]
            return {
                "status": result["status"],
                "capture_count": int(result["capture_count"]),
                "duration_seconds": float(
                    result.get("wall_duration_seconds", result.get("duration_seconds", 0.0))
                ),
            }

        baseline_examples[path] = {
            "reference": result_record("matplotlib"),
            "xy": result_record("xy"),
            "capture_parity": True,
            "dimension_parity": bool(comparison.get("exact_dimension_parity")),
            "dimension_gate_passed": True,
            "exact_dimension_parity": bool(comparison.get("exact_dimension_parity")),
            "visual_gate_passed": True,
            "visual_decisions": [
                pair["visual_gate"]["decision"] for pair in comparison["figure_pairs"]
            ],
            "semantic_gate_passed": True,
            "behavior_gate_passed": True,
            "temporary_waivers": [],
        }
        manifest_by_path[path]["temporary_waivers"] = []

    manifest_bytes = _json_bytes(manifest)
    promoted_manifest_sha256 = _sha256(manifest_bytes)
    for record in report_records:
        record["promoted_manifest_sha256"] = promoted_manifest_sha256

    baseline["schema_version"] = 3
    baseline["audit_commit"] = audit_commit
    baseline["harness_version"] = HARNESS_VERSION
    baseline["manifest_sha256"] = promoted_manifest_sha256
    baseline["extended_spec_sha256"] = extended_spec_sha256
    baseline["acceptance_reports"] = sorted(
        report_records,
        key=lambda record: (str(record["profile"]), str(record["sha256"])),
    )
    baseline["summary"] = _promoted_summary(
        manifest=manifest,
        baseline_examples=baseline_examples,
    )
    manifest_path.write_bytes(manifest_bytes)
    baseline_path.write_bytes(_json_bytes(baseline))
    return manifest, baseline


def verify_monotonic_baseline(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> list[str]:
    """Reject baseline regressions and newly introduced waiver categories."""

    errors: list[str] = []
    previous_examples = previous.get("examples", {})
    current_examples = current.get("examples", {})
    if set(previous_examples) != set(current_examples):
        errors.append("baseline example paths changed")
        return errors

    for path, old in previous_examples.items():
        new = current_examples[path]
        if old["xy"]["status"] == "passed" and new["xy"]["status"] != "passed":
            errors.append(f"{path}: xy execution regressed")
        if old.get("capture_parity") and not new.get("capture_parity"):
            errors.append(f"{path}: capture parity regressed")
        old_dimension_gate = old.get("dimension_gate_passed")
        new_dimension_gate = new.get("dimension_gate_passed")
        if old_dimension_gate and not new_dimension_gate:
            errors.append(f"{path}: dimension acceptance gate regressed")
        if old.get("visual_gate_passed") and not new.get("visual_gate_passed"):
            errors.append(f"{path}: visual gate regressed")
        if old.get("semantic_gate_passed") and not new.get("semantic_gate_passed"):
            errors.append(f"{path}: semantic gate regressed")
        if old.get("behavior_gate_passed") and not new.get("behavior_gate_passed"):
            errors.append(f"{path}: behavior gate regressed")
        added = _waiver_keys(new) - _waiver_keys(old)
        if added:
            errors.append(f"{path}: added temporary waivers: {sorted(added)}")
    return errors


def verify_contract(root: Path = CORPUS_ROOT) -> list[str]:
    """Verify source bytes, AST proofs, classifications, and baseline shape."""

    errors: list[str] = []
    manifest_path = root / "manifest.json"
    baseline_path = root / "baseline.json"
    provenance_path = root / "provenance.json"
    extended_spec_path = root / "extended-environment.json"
    for path in (
        manifest_path,
        baseline_path,
        provenance_path,
        extended_spec_path,
        root / "LICENSE",
        root / "README.md",
    ):
        if not path.is_file():
            errors.append(f"missing contract file: {path}")
    if errors:
        return errors

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    extended_spec = json.loads(extended_spec_path.read_text(encoding="utf-8"))
    from .extended_environment import validate_spec

    errors.extend(validate_spec(extended_spec, manifest_path=manifest_path))
    entries = manifest.get("examples", [])
    raw_baseline_examples = baseline.get("examples")
    baseline_examples = raw_baseline_examples if isinstance(raw_baseline_examples, dict) else {}
    if (
        len(entries) != CONTRACT_SOURCE_COUNT
        or manifest.get("source_count") != CONTRACT_SOURCE_COUNT
    ):
        errors.append(f"manifest must contain exactly {CONTRACT_SOURCE_COUNT} source entries")

    paths = [entry.get("path") for entry in entries]
    if len(set(paths)) != len(paths):
        errors.append("manifest contains duplicate source paths")
    excluded_paths = sorted(
        path for path in paths if isinstance(path, str) and _is_excluded_3d_example(path)
    )
    if excluded_paths:
        errors.append(
            "manifest contains sources excluded from XY's 2-D contract: "
            + ", ".join(excluded_paths[:10])
        )
    actual_paths = {
        path.relative_to(root / "examples").as_posix() for path in (root / "examples").rglob("*.py")
    }
    if set(paths) != actual_paths:
        errors.append("vendored source paths do not exactly match the manifest")

    counts: Counter[str] = Counter()
    eligible_count = 0
    for entry in entries:
        relative = entry["path"]
        source_path = root / "examples" / relative
        if not source_path.is_file():
            continue
        source_bytes = source_path.read_bytes()
        if _sha256(source_bytes) != entry.get("sha256"):
            errors.append(f"{relative}: source sha256 mismatch")
        if len(source_bytes) != entry.get("byte_count"):
            errors.append(f"{relative}: source byte count mismatch")
        try:
            source = source_bytes.decode("utf-8")
            tree = ast.parse(source, filename=relative)
        except (UnicodeDecodeError, SyntaxError) as exc:
            errors.append(f"{relative}: source does not parse: {exc}")
            continue
        normalized = _normalized_script_ast(source, relative)
        if _sha256(normalized.encode()) != entry.get("normalized_ast_sha256"):
            errors.append(f"{relative}: normalized AST hash mismatch")
        if entry.get("notebook_code_ast_sha256") != entry.get("normalized_ast_sha256"):
            errors.append(f"{relative}: notebook/source AST proof hash mismatch")
        imports = pyplot_imports(tree)
        eligible = bool(imports)
        if eligible != entry.get("pyplot_eligible"):
            errors.append(f"{relative}: pyplot eligibility mismatch")
        if imports != entry.get("pyplot_imports"):
            errors.append(f"{relative}: pyplot import inventory mismatch")
        render_class, behavior = _classify_source(tree, relative)
        if render_class != entry.get("render_class"):
            errors.append(f"{relative}: render class mismatch")
        if behavior != entry.get("behavior"):
            errors.append(f"{relative}: behavior classification mismatch")
        dimension_policy = _dimension_policy(tree)
        if dimension_policy != entry.get("dimension_policy"):
            errors.append(f"{relative}: dimension policy mismatch")
        eligible_count += eligible
        counts[str(entry.get("profile"))] += 1
        if entry.get("notebook_ast_matches") is not True:
            errors.append(f"{relative}: notebook AST proof is not true")
        for waiver in entry.get("temporary_waivers", []):
            if waiver.get("temporary") is not True:
                errors.append(f"{relative}: non-temporary waiver is forbidden")
        baseline_entry = baseline_examples.get(relative)
        if not isinstance(baseline_entry, dict):
            continue
        if baseline_entry.get("temporary_waivers") != entry.get("temporary_waivers"):
            errors.append(f"{relative}: manifest and baseline waivers differ")
        waiver_ids = _waiver_keys(baseline_entry)
        if (
            eligible
            and baseline_entry.get("reference", {}).get("status") != "passed"
            and "reference-environment" not in waiver_ids
        ):
            errors.append(f"{relative}: reference failure has no explicit waiver")
        if (
            eligible
            and baseline_entry.get("xy", {}).get("status") != "passed"
            and "xy-execution" not in waiver_ids
        ):
            errors.append(f"{relative}: xy execution failure has no explicit waiver")
        if eligible and baseline_entry.get("xy", {}).get("status") == "passed":
            if not baseline_entry.get("capture_parity") and "capture-structure" not in waiver_ids:
                errors.append(f"{relative}: capture failure has no explicit waiver")
            dimension_accepted = baseline_entry.get(
                "dimension_gate_passed",
                baseline_entry.get("dimension_parity"),
            )
            if (
                baseline_entry.get("capture_parity")
                and not dimension_accepted
                and "canvas-dimensions" not in waiver_ids
            ):
                errors.append(f"{relative}: canvas-dimension failure has no explicit waiver")
            if (
                baseline_entry.get("capture_parity")
                and baseline_entry.get("visual_gate_passed") is not True
                and not any(
                    waiver_id == "visual-format" or waiver_id.startswith("visual-issue-")
                    for waiver_id in waiver_ids
                )
            ):
                errors.append(f"{relative}: visual failure has no explicit waiver")
        if not eligible and waiver_ids:
            errors.append(f"{relative}: non-pyplot source must not carry pyplot waivers")

    if (
        eligible_count != PYPLOT_ELIGIBLE_COUNT
        or manifest.get("pyplot_eligible_count") != PYPLOT_ELIGIBLE_COUNT
    ):
        errors.append(
            f"contract must classify exactly {PYPLOT_ELIGIBLE_COUNT} pyplot-eligible examples"
        )
    if manifest.get("gallery_adapters") != ALLOWED_GALLERY_ADAPTERS:
        errors.append("gallery adapter allowlist differs from the reviewed contract")
    if manifest.get("gallery_documentation_version") != GALLERY_DOCUMENTATION_VERSION:
        errors.append("gallery documentation snapshot version is incorrect")
    if manifest.get("gallery_snapshot_downloaded_on") != GALLERY_SNAPSHOT_DOWNLOADED_ON:
        errors.append("gallery snapshot download date is incorrect")
    if manifest.get("matplotlib_version") != COMPATIBILITY_ORACLE_VERSION:
        errors.append("compatibility oracle version is incorrect")
    if (
        dict(counts) != EXPECTED_PROFILE_COUNTS
        or manifest.get("profile_counts") != EXPECTED_PROFILE_COUNTS
    ):
        errors.append(f"profile counts differ from {EXPECTED_PROFILE_COUNTS}: {dict(counts)}")
    baseline_paths_match = set(baseline_examples) == set(paths)
    if not baseline_paths_match:
        errors.append("baseline paths do not exactly match the manifest")

    if baseline.get("schema_version") in {2, 3}:
        expected_summary: dict[str, Any] = {}
        if baseline_paths_match:
            expected_summary = _promoted_summary(
                manifest=manifest,
                baseline_examples=baseline_examples,
            )
            if expected_summary["acceptance_complete"] is not True:
                errors.append(
                    f"promoted baseline must accept all {PYPLOT_ELIGIBLE_COUNT} pyplot examples"
                )
            if expected_summary["temporary_waiver_count"] != 0:
                errors.append("promoted baseline must contain zero temporary waivers")
        if baseline.get("schema_version") == 3:
            if COMMIT_SHA_PATTERN.fullmatch(str(baseline.get("audit_commit", ""))) is None:
                errors.append("promoted baseline audit_commit must be a 40-character SHA")
            if baseline.get("harness_version") != HARNESS_VERSION:
                errors.append("promoted baseline harness version is stale")
            if baseline.get("manifest_sha256") != _sha256(manifest_path.read_bytes()):
                errors.append("promoted baseline manifest hash is stale")
            if baseline.get("extended_spec_sha256") != _sha256(extended_spec_path.read_bytes()):
                errors.append("promoted baseline extended environment hash is stale")
            acceptance_reports = baseline.get("acceptance_reports")
            expected_acceptance_profiles = {
                str(entry["profile"]) for entry in entries if entry.get("pyplot_eligible")
            }
            records_valid = isinstance(acceptance_reports, list) and all(
                isinstance(record, dict) for record in acceptance_reports
            )
            if not records_valid or not acceptance_reports:
                errors.append("promoted baseline acceptance report provenance is invalid")
            else:
                assert isinstance(acceptance_reports, list)
                report_manifest_sha256s = {
                    record.get("report_manifest_sha256") for record in acceptance_reports
                }
                if (
                    {record.get("profile") for record in acceptance_reports}
                    != expected_acceptance_profiles
                    or len(report_manifest_sha256s) != 1
                    or any(
                        record.get("harness_version") != HARNESS_VERSION
                        or SHA256_PATTERN.fullmatch(str(record.get("sha256", ""))) is None
                        or record.get("implementation_commit") != baseline.get("audit_commit")
                        or SHA256_PATTERN.fullmatch(str(record.get("report_manifest_sha256", "")))
                        is None
                        or record.get("promoted_manifest_sha256") != baseline.get("manifest_sha256")
                        or record.get("extended_spec_sha256")
                        != baseline.get("extended_spec_sha256")
                        or (
                            "python_interpreter" in record
                            and not valid_python_interpreter(record["python_interpreter"])
                        )
                        for record in acceptance_reports
                    )
                ):
                    errors.append("promoted baseline acceptance report provenance is invalid")
    else:
        if baseline.get("audit_commit") != LEGACY_SCHEMA_ONE_AUDIT_COMMIT:
            errors.append("schema-1 baseline audit_commit is not the pinned historical audit")
        expected_summary = dict(LEGACY_SCHEMA_ONE_SUMMARY) if baseline_paths_match else {}
    for key, expected in expected_summary.items():
        if baseline.get("summary", {}).get(key) != expected:
            errors.append(f"baseline summary {key} must be {expected}")

    for kind, expected in EXPECTED_ARCHIVES.items():
        recorded = provenance.get("archives", {}).get(kind, {})
        if recorded.get("sha256") != expected["sha256"] or recorded.get("url") != expected["url"]:
            errors.append(f"{kind} archive provenance mismatch")
        manifest_archive = manifest.get("archives", {}).get(kind, {})
        if (
            manifest_archive.get("sha256") != expected["sha256"]
            or manifest_archive.get("url") != expected["url"]
            or manifest_archive.get("member_count") != ARCHIVE_SOURCE_COUNT
        ):
            errors.append(f"{kind} archive manifest metadata mismatch")
    if provenance.get("gallery_documentation_version") != GALLERY_DOCUMENTATION_VERSION:
        errors.append("provenance gallery documentation version mismatch")
    if provenance.get("compatibility_oracle_version") != COMPATIBILITY_ORACLE_VERSION:
        errors.append("provenance compatibility oracle version mismatch")
    if provenance.get("downloaded_on") != GALLERY_SNAPSHOT_DOWNLOADED_ON:
        errors.append("provenance download date mismatch")
    return errors


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="verify the checked-in contract")
    check.add_argument("--root", type=Path, default=CORPUS_ROOT)
    check.add_argument("--previous-baseline", type=Path)

    build = subparsers.add_parser("build", help="rebuild from the two official archives")
    build.add_argument("--python-archive", type=Path, required=True)
    build.add_argument("--notebook-archive", type=Path, required=True)
    build.add_argument("--audit-summary", type=Path, required=True)
    build.add_argument("--destination", type=Path, default=CORPUS_ROOT)

    promote = subparsers.add_parser(
        "promote",
        help="replace all temporary waivers from complete accepted reports",
    )
    promote.add_argument("--report", type=Path, action="append", required=True)
    promote.add_argument("--root", type=Path, default=CORPUS_ROOT)
    promote.add_argument(
        "--audit-commit",
        required=True,
        help="40-character implementation commit exercised by every report",
    )

    args = parser.parse_args()
    if args.command == "build":
        manifest, baseline = build_contract(
            python_archive=args.python_archive,
            notebook_archive=args.notebook_archive,
            audit_summary=args.audit_summary,
            destination=args.destination,
        )
        print(
            json.dumps(
                {
                    "source_count": manifest["source_count"],
                    "pyplot_eligible_count": manifest["pyplot_eligible_count"],
                    **baseline["summary"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "promote":
        _manifest, baseline = promote_reports(
            args.report,
            audit_commit=args.audit_commit,
            root=args.root,
        )
        print(json.dumps(baseline["summary"], indent=2, sort_keys=True))
        return 0

    errors = verify_contract(args.root)
    if args.previous_baseline:
        previous = json.loads(args.previous_baseline.read_text(encoding="utf-8"))
        current = json.loads((args.root / "baseline.json").read_text(encoding="utf-8"))
        errors.extend(verify_monotonic_baseline(previous, current))
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors), file=sys.stderr)
        return 1
    print(
        "Matplotlib gallery contract verified: "
        f"{CONTRACT_SOURCE_COUNT} sources, {PYPLOT_ELIGIBLE_COUNT} pyplot eligible"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
