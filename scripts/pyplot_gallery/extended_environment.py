"""Reproducible environment contract for the 13 extended gallery examples."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .contract import CORPUS_ROOT, MANIFEST_PATH
from .integrity import capture_integrity_errors

SPEC_PATH = CORPUS_ROOT / "extended-environment.json"

SYSTEM_PACKAGES = (
    "cm-super",
    "dvipng",
    "fonts-dejavu-core",
    "fonts-liberation",
    "fonts-urw-base35",
    "ghostscript",
    "gir1.2-gtk-3.0",
    "gir1.2-gtk-4.0",
    "librsvg2-common",
    "python3-cairo",
    "python3-gi",
    "python3-gi-cairo",
    "python3-venv",
    "texlive-fonts-recommended",
    "texlive-latex-base",
    "texlive-latex-extra",
    "texlive-latex-recommended",
    "xauth",
    "xvfb",
)
PYTHON_PACKAGES = (
    "colorspacious==1.1.2",
    "matplotlib==3.11.0",
)
REQUIRED_COMMANDS = (
    "dvipng",
    "dvips",
    "fc-match",
    "gs",
    "kpsewhich",
    "latex",
    "xvfb-run",
    "Xvfb",
)
TEX_FILES = (
    "article.cls",
    "fix-cm.sty",
    "ptmr8r.tfm",
    "ptmri8r.tfm",
    "ptmro8r.tfm",
    "ptmr8rn.tfm",
    "ptmrr8re.tfm",
)

TRIANGLE_POINTS = ((0.20, 0.20), (0.80, 0.20), (0.50, 0.80))

EXAMPLE_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "event_handling/ginput_manual_clabel_sgskip.py": {
        "requirements": ["deterministic_input"],
        "backends": {
            "matplotlib": "Agg",
            "xy": "module://xy.backends.backend_xy",
        },
        "argv": [],
        "timeout_seconds": 120,
        "driver": {
            "waitforbuttonpress": [False, True, False],
            "ginput": [
                {"points": [list(point) for point in TRIANGLE_POINTS], "button": 1},
                {"points": [], "button": 2},
            ],
            "manual_clabel": [[0.0, 0.0]],
            "sleep_scale": 0.0,
        },
        "expected_outputs": [{"kind": "figure", "count": 1}],
    },
    "misc/multipage_pdf.py": {
        "requirements": ["tex", "tex_fonts"],
        "backends": {
            "matplotlib": "Agg",
            "xy": "module://xy.backends.backend_xy",
        },
        "argv": [],
        "timeout_seconds": 180,
        "driver": {},
        "expected_outputs": [
            {
                "kind": "figure",
                "count": 3,
            },
            {
                "kind": "pdf",
                "path": "multipage_pdf.pdf",
                "page_count": 3,
            },
        ],
    },
    "misc/multiprocess_sgskip.py": {
        "requirements": ["multiprocessing"],
        "backends": {
            "matplotlib": "Agg",
            "xy": "module://xy.backends.backend_xy",
        },
        "argv": [],
        "timeout_seconds": 120,
        "driver": {
            "multiprocessing_start_method": "fork",
            "show_policy": "native_until_close",
            "checkpoint_after_seconds": 1.0,
            "checkpoint_line_count": 2,
            "poll_interval_seconds": 0.02,
        },
        "expected_outputs": [{"kind": "figure", "count": 1, "process": "child"}],
    },
    "mplot3d/pathpatch3d.py": {
        "requirements": ["tex", "tex_fonts"],
        "backends": {
            "matplotlib": "Agg",
            "xy": "module://xy.backends.backend_xy",
        },
        "argv": [],
        "timeout_seconds": 180,
        "driver": {},
        "expected_outputs": [{"kind": "figure", "count": 1}],
    },
    "text_labels_and_annotations/demo_text_path.py": {
        "requirements": ["tex", "tex_fonts"],
        "backends": {
            "matplotlib": "Agg",
            "xy": "module://xy.backends.backend_xy",
        },
        "argv": [],
        "timeout_seconds": 180,
        "driver": {},
        "expected_outputs": [{"kind": "figure", "count": 1}],
    },
    "text_labels_and_annotations/font_table.py": {
        "requirements": ["clean_argv", "system_fonts"],
        "backends": {
            "matplotlib": "Agg",
            "xy": "module://xy.backends.backend_xy",
        },
        "argv": [],
        "timeout_seconds": 120,
        "driver": {},
        "expected_outputs": [{"kind": "figure", "count": 1}],
    },
    "text_labels_and_annotations/tex_demo.py": {
        "requirements": ["tex", "tex_fonts"],
        "backends": {
            "matplotlib": "Agg",
            "xy": "module://xy.backends.backend_xy",
        },
        "argv": [],
        "timeout_seconds": 180,
        "driver": {},
        "expected_outputs": [{"kind": "figure", "count": 2}],
    },
    "text_labels_and_annotations/usetex_baseline_test.py": {
        "requirements": ["tex", "tex_fonts"],
        "backends": {
            "matplotlib": "Agg",
            "xy": "module://xy.backends.backend_xy",
        },
        "argv": [],
        "timeout_seconds": 180,
        "driver": {},
        "expected_outputs": [{"kind": "figure", "count": 1}],
    },
    "text_labels_and_annotations/usetex_fonteffects.py": {
        "requirements": ["tex", "tex_fonts"],
        "backends": {
            "matplotlib": "Agg",
            "xy": "module://xy.backends.backend_xy",
        },
        "argv": [],
        "timeout_seconds": 180,
        "driver": {},
        "expected_outputs": [{"kind": "figure", "count": 1}],
    },
    "user_interfaces/mplcvd.py": {
        "requirements": ["colorspacious"],
        "backends": {
            "matplotlib": "Agg",
            "xy": "module://xy.backends.backend_xy",
        },
        "argv": [],
        "timeout_seconds": 120,
        "driver": {
            "color_filters": ["Greyscale", "Deuteranopia"],
        },
        "expected_outputs": [{"kind": "figure", "count": 1}],
    },
    "user_interfaces/pylab_with_gtk3_sgskip.py": {
        "requirements": ["gtk3", "gui_backend"],
        "backends": {
            "matplotlib": "GTK3Agg",
            "xy": "module://xy.backends.backend_xy",
        },
        "argv": [],
        "timeout_seconds": 120,
        "driver": {"motion": [[320, 240]], "toolbar_action": "Click me"},
        "expected_outputs": [{"kind": "figure", "count": 1}],
    },
    "user_interfaces/pylab_with_gtk4_sgskip.py": {
        "requirements": ["gtk4", "gui_backend"],
        "backends": {
            "matplotlib": "GTK4Agg",
            "xy": "module://xy.backends.backend_xy",
        },
        "argv": [],
        "timeout_seconds": 120,
        "driver": {"motion": [[320, 240]], "toolbar_action": "Click me"},
        "expected_outputs": [{"kind": "figure", "count": 1}],
    },
    "user_interfaces/toolmanager_sgskip.py": {
        "requirements": ["gtk3", "gui_backend", "toolmanager"],
        "backends": {
            "matplotlib": "GTK3Agg",
            "xy": "module://xy.backends.backend_xy",
        },
        "argv": [],
        "timeout_seconds": 120,
        "driver": {"tool_triggers": ["List", "Show", "Show"]},
        "expected_outputs": [{"kind": "figure", "count": 1}],
    },
}


def generated_spec() -> dict[str, Any]:
    """Return the canonical checked-in extended environment description."""

    return {
        "schema_version": 1,
        "matplotlib_version": "3.11.0",
        "profile": "extended",
        "example_count": 13,
        "platform": {
            "github_runner": "ubuntu-24.04",
            "python": "/usr/bin/python3",
            "venv_system_site_packages": True,
            "display": ('xvfb-run --auto-servernum --server-args="-screen 0 1280x720x24"'),
        },
        "system_packages": list(SYSTEM_PACKAGES),
        "python_packages": list(PYTHON_PACKAGES),
        "required_commands": list(REQUIRED_COMMANDS),
        "tex_files": list(TEX_FILES),
        "examples": [
            {"path": path, **requirements}
            for path, requirements in sorted(EXAMPLE_REQUIREMENTS.items())
        ],
    }


def write_spec(destination: Path) -> None:
    """Write the generated metadata next to a rebuilt gallery manifest."""

    destination.joinpath("extended-environment.json").write_text(
        json.dumps(generated_spec(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_spec(path: Path = SPEC_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _example_map(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    examples = spec.get("examples", [])
    if not isinstance(examples, list):
        return {}
    return {
        str(example.get("path")): example
        for example in examples
        if isinstance(example, dict) and isinstance(example.get("path"), str)
    }


def validate_spec(
    spec: dict[str, Any],
    *,
    manifest_path: Path = MANIFEST_PATH,
) -> list[str]:
    """Check exact dependencies, paths, drivers, and profile membership."""

    errors: list[str] = []
    canonical = generated_spec()
    if spec != canonical:
        errors.append("extended environment metadata differs from the generated contract")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [*errors, f"cannot load gallery manifest: {exc}"]
    expected_paths = {
        str(entry["path"])
        for entry in manifest.get("examples", [])
        if entry.get("profile") == "extended" and entry.get("pyplot_eligible") is True
    }
    examples = spec.get("examples", [])
    actual_paths = {str(example.get("path")) for example in examples if isinstance(example, dict)}
    if len(examples) != 13 or spec.get("example_count") != 13:
        errors.append("extended environment must describe exactly 13 examples")
    if actual_paths != expected_paths:
        errors.append(
            "extended environment paths differ from the manifest: "
            f"missing={sorted(expected_paths - actual_paths)}, "
            f"unexpected={sorted(actual_paths - expected_paths)}"
        )
    for example in examples:
        if not isinstance(example, dict):
            errors.append("extended environment example entries must be objects")
            continue
        path = str(example.get("path"))
        if example.get("argv") != []:
            errors.append(f"{path}: extended examples require a clean empty argv")
        if not example.get("requirements"):
            errors.append(f"{path}: environment requirements are missing")
        backends = example.get("backends")
        if not isinstance(backends, dict) or backends.get("matplotlib") not in {
            "Agg",
            "GTK3Agg",
            "GTK4Agg",
        }:
            errors.append(f"{path}: unsupported or missing Matplotlib reference backend")
        if not isinstance(backends, dict) or backends.get("xy") != (
            "module://xy.backends.backend_xy"
        ):
            errors.append(f"{path}: xy runs must use the XY backend")
        if not example.get("expected_outputs"):
            errors.append(f"{path}: expected output contract is missing")
    return errors


def preflight_errors(spec: dict[str, Any]) -> list[str]:
    """Probe the external programs and imports used by the extended CI image."""

    errors: list[str] = []
    for command in spec.get("required_commands", []):
        if shutil.which(str(command)) is None:
            errors.append(f"required command is unavailable: {command}")

    for package, version in (("colorspacious", "1.1.2"), ("matplotlib", "3.11.0")):
        if importlib.util.find_spec(package) is None:
            errors.append(f"required Python package is unavailable: {package}=={version}")
            continue
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            errors.append(f"cannot determine installed version of {package}")
        else:
            if actual != version:
                errors.append(f"{package} version {actual} != required {version}")

    if importlib.util.find_spec("gi") is None:
        errors.append("required system Python module is unavailable: gi")
    else:
        for namespace, version in (("Gtk", "3.0"), ("Gtk", "4.0")):
            # GI permits only one version of a namespace per process. Probe
            # GTK3 and GTK4 in separate interpreters so successfully loading
            # one cannot make the other fail with a false version conflict.
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import gi; "
                        f"gi.require_version({namespace!r}, {version!r}); "
                        f"from gi.repository import {namespace}"
                    ),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if completed.returncode:
                errors.append(
                    f"GI namespace {namespace} {version} is unavailable: "
                    f"{(completed.stderr or completed.stdout).strip()}"
                )
        svg_loader = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import gi; "
                    "gi.require_version('GdkPixbuf', '2.0'); "
                    "from gi.repository import GdkPixbuf; "
                    "loader = GdkPixbuf.PixbufLoader.new_with_type('svg'); "
                    'loader.write(b\'<svg xmlns="http://www.w3.org/2000/svg" '
                    'width="2" height="2"><rect width="2" height="2"/></svg>\'); '
                    "loader.close()"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if svg_loader.returncode:
            errors.append(
                "GDK Pixbuf SVG loader is unavailable: "
                f"{(svg_loader.stderr or svg_loader.stdout).strip()}"
            )

    if not os.environ.get("DISPLAY"):
        errors.append("DISPLAY is unset; run the preflight under xvfb-run")

    kpsewhich = shutil.which("kpsewhich")
    if kpsewhich is not None:
        for filename in spec.get("tex_files", []):
            completed = subprocess.run(
                [kpsewhich, str(filename)],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if completed.returncode or not completed.stdout.strip():
                errors.append(f"TeX file is unavailable: {filename}")

    if importlib.util.find_spec("matplotlib") is not None:
        try:
            from matplotlib import font_manager

            default_font = Path(font_manager.findfont("DejaVu Sans"))
            if not default_font.is_file():
                errors.append(f"default DejaVu Sans font is unavailable: {default_font}")
        except (ImportError, OSError, ValueError) as exc:
            errors.append(f"cannot resolve the default system font: {exc}")
    return errors


def validate_complete_report(
    report: dict[str, Any],
    *,
    spec: dict[str, Any],
) -> list[str]:
    """Require complete 13/13 execution and acceptance, ignoring no waiver."""

    errors: list[str] = []
    expected = _example_map(spec)
    cases = report.get("examples", [])
    actual = {
        str(case.get("path")): case
        for case in cases
        if isinstance(case, dict) and isinstance(case.get("path"), str)
    }
    if report.get("summary", {}).get("profile") != "extended":
        errors.append("report profile is not extended")
    if report.get("summary", {}).get("selected_examples") != 13:
        errors.append("extended report did not select exactly 13 examples")
    if set(actual) != set(expected):
        errors.append(
            "extended report paths differ from the environment contract: "
            f"missing={sorted(set(expected) - set(actual))}, "
            f"unexpected={sorted(set(actual) - set(expected))}"
        )

    for path, requirements in expected.items():
        case = actual.get(path)
        if case is None:
            continue
        if case.get("temporary_waivers"):
            errors.append(f"{path}: temporary waivers remain")
        engines = case.get("engines", {})
        for engine in ("matplotlib", "xy"):
            result = engines.get(engine, {})
            if result.get("status") != "passed":
                errors.append(f"{path}: {engine} did not complete")
            errors.extend(
                f"{path}: {engine} {reason}" for reason in capture_integrity_errors(engine, result)
            )
            extended_driver = result.get("extended_driver", {})
            driver_contract = (
                extended_driver.get("driver_contract", {})
                if isinstance(extended_driver, dict)
                else {}
            )
            if driver_contract.get("status") != "passed":
                errors.append(f"{path}: {engine} extended driver evidence did not pass")
        comparison = case.get("comparison", {})
        for field in (
            "capture_parity",
            "dimension_gate_passed",
            "visual_gate_passed",
            "semantic_gate_passed",
        ):
            if comparison.get(field) is not True:
                errors.append(f"{path}: {field} did not pass")
        if comparison.get("behavior_gate_passed") is not True:
            errors.append(f"{path}: behavior gate did not pass")
        expected_outputs = requirements.get("expected_outputs", [])
        for expected_output in expected_outputs:
            if expected_output.get("kind") == "figure":
                expected_count = expected_output.get("count")
                for engine in ("matplotlib", "xy"):
                    actual_count = case.get("engines", {}).get(engine, {}).get("capture_count")
                    if actual_count != expected_count:
                        errors.append(
                            f"{path}: {engine} capture count {actual_count} != {expected_count}"
                        )
                continue
            if expected_output.get("kind") != "pdf":
                continue
            for engine in ("matplotlib", "xy"):
                artifacts = case.get("engines", {}).get(engine, {}).get("output_artifacts", [])
                match = next(
                    (
                        artifact
                        for artifact in artifacts
                        if artifact.get("path") == expected_output["path"]
                    ),
                    None,
                )
                if match is None:
                    errors.append(f"{path}: {engine} did not record {expected_output['path']}")
                elif match.get("page_count") != expected_output["page_count"]:
                    errors.append(
                        f"{path}: {engine} PDF page count "
                        f"{match.get('page_count')} != {expected_output['page_count']}"
                    )
    return errors


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="validate checked-in setup metadata")
    check.add_argument("--spec", type=Path, default=SPEC_PATH)
    check.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    preflight = subparsers.add_parser(
        "preflight", help="probe TeX, fonts, optional imports, and GUI display"
    )
    preflight.add_argument("--spec", type=Path, default=SPEC_PATH)
    report = subparsers.add_parser(
        "verify-report", help="require complete 13/13 extended gallery acceptance"
    )
    report.add_argument("report", type=Path)
    report.add_argument("--spec", type=Path, default=SPEC_PATH)
    args = parser.parse_args()

    spec = load_spec(args.spec)
    if args.command == "check":
        errors = validate_spec(spec, manifest_path=args.manifest)
    elif args.command == "preflight":
        errors = [*validate_spec(spec), *preflight_errors(spec)]
    else:
        payload = json.loads(args.report.read_text(encoding="utf-8"))
        errors = [*validate_spec(spec), *validate_complete_report(payload, spec=spec)]
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors), file=sys.stderr)
        return 1
    if args.command == "verify-report":
        print("Extended gallery verified: 13/13 examples complete with no waivers")
    elif args.command == "preflight":
        print("Extended gallery environment verified")
    else:
        print("Extended gallery metadata verified: 13 examples")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
