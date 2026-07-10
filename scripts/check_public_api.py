#!/usr/bin/env python3
"""Verify the lazy public API surface is coherent.

`fastcharts.__init__` intentionally hand-maintains two things:

- `__all__`, the names users can import from `fastcharts`
- `_EXPORTS`, the lazy export map that keeps `import fastcharts` lightweight

That is a good shape for import-time performance, but it is easy to forget one
side when adding a chart family. This stdlib-only check catches drift before a
release or CI green build.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
IMPORT_BUDGET_MS = 200.0
HEAVY_THIRD_PARTY_IMPORTS = {
    "anywidget",
    "numpy",
    "traitlets",
}
HEAVY_FASTCHARTS_IMPORTS = {
    "fastcharts.channels",
    "fastcharts.channel",
    "fastcharts.columns",
    "fastcharts.components",
    "fastcharts.figure",
    "fastcharts.interaction",
    "fastcharts.kernels",
    "fastcharts.lod",
    "fastcharts.marks",
    "fastcharts._native",
    "fastcharts.widget",
}
HEAVY_IMPORTS = HEAVY_THIRD_PARTY_IMPORTS | HEAVY_FASTCHARTS_IMPORTS
COMPONENT_REEXPORTS = {"CHART_DOM_SLOTS"}
DECLARATIVE_MARK_EXPORTS = (
    "scatter",
    "line",
    "area",
    "histogram",
    "hist",
    "bar",
    "column",
    "heatmap",
)
DECLARATIVE_ANNOTATION_EXPORTS = (
    "arrow",
    "callout",
    "label",
    "marker",
    "threshold",
    "threshold_zone",
    "vline",
    "hline",
    "x_band",
    "y_band",
    "text",
)
DECLARATIVE_AXIS_EXPORTS = ("x_axis", "y_axis")
DECLARATIVE_CHROME_EXPORTS = (
    "legend",
    "tooltip",
    "modebar",
    "theme",
    "mark_style",
    "interaction_config",
)
DECLARATIVE_CHART_EXPORTS = (
    "chart",
    "scatter_chart",
    "line_chart",
    "area_chart",
    "histogram_chart",
    "bar_chart",
    "column_chart",
    "heatmap_chart",
)
DECLARATIVE_CHART_READOUTS = (
    "figure",
    "widget",
    "show",
    "to_html",
    "html",
    "_repr_html_",
    "to_png",
    "memory_report",
    "chrome_components",
    "reflex_components",
)
DECLARATIVE_API_EXPORTS = (
    *DECLARATIVE_MARK_EXPORTS,
    *DECLARATIVE_ANNOTATION_EXPORTS,
    *DECLARATIVE_AXIS_EXPORTS,
    *DECLARATIVE_CHROME_EXPORTS,
    *DECLARATIVE_CHART_EXPORTS,
)


def _string_list(value: Any, label: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{label} must be a list[str], got {type(value).__name__}")
        return []
    names: list[str] = []
    for item in value:
        if not isinstance(item, str):
            errors.append(f"{label} must contain only strings, got {item!r}")
            continue
        names.append(item)
    return names


def validate_public_api(pkg: ModuleType) -> list[str]:
    """Return human-readable public API drift findings for a package module."""
    errors: list[str] = []
    public_names = _string_list(getattr(pkg, "__all__", None), "__all__", errors)

    exports = getattr(pkg, "_EXPORTS", None)
    if not isinstance(exports, dict):
        errors.append(f"_EXPORTS must be a dict[str, str], got {type(exports).__name__}")
        return errors

    for name, module_name in exports.items():
        if not isinstance(name, str):
            errors.append(f"_EXPORTS key must be str, got {name!r}")
        if not isinstance(module_name, str) or not module_name.startswith("."):
            errors.append(f"_EXPORTS[{name!r}] must be a relative module path, got {module_name!r}")

    public_set = set(public_names)
    if len(public_set) != len(public_names):
        dupes = sorted({name for name in public_names if public_names.count(name) > 1})
        errors.append(f"__all__ contains duplicate names: {dupes}")

    expected = set(exports) | {"__version__"}
    missing = sorted(expected - public_set)
    extra = sorted(public_set - expected)
    if missing:
        errors.append(f"__all__ is missing lazy exports: {missing}")
    if extra:
        errors.append(f"__all__ contains names not in _EXPORTS/__version__: {extra}")

    dir_names = set(dir(pkg))
    dir_missing = sorted(public_set - dir_names)
    if dir_missing:
        errors.append(f"dir(fastcharts) is missing public names: {dir_missing}")

    for name, module_name in sorted(exports.items()):
        if not isinstance(name, str) or not isinstance(module_name, str):
            continue
        try:
            module = importlib.import_module(module_name, pkg.__name__)
        except Exception as exc:
            errors.append(f"{name}: cannot import {module_name!r}: {exc!r}")
            continue
        if not hasattr(module, name):
            errors.append(f"{name}: {module.__name__} does not define the exported name")

    return errors


def validate_component_public_api(
    pkg: ModuleType, components_module: ModuleType | None = None
) -> list[str]:
    """Ensure the composition API submodule advertises the same root exports."""
    errors: list[str] = []
    exports = getattr(pkg, "_EXPORTS", None)
    if not isinstance(exports, dict):
        return ["cannot validate component API because _EXPORTS is not a dict[str, str]"]

    if components_module is None:
        try:
            components_module = importlib.import_module(".components", pkg.__name__)
        except Exception as exc:
            return [f"cannot import fastcharts.components for public API validation: {exc!r}"]

    names = _string_list(
        getattr(components_module, "__all__", None),
        f"{components_module.__name__}.__all__",
        errors,
    )
    name_set = set(names)
    if len(name_set) != len(names):
        dupes = sorted({name for name in names if names.count(name) > 1})
        errors.append(f"{components_module.__name__}.__all__ contains duplicate names: {dupes}")

    component_exports = {
        name
        for name, module_name in exports.items()
        if module_name == ".components" and isinstance(name, str)
    }
    missing = sorted(component_exports - name_set)
    allowed_reexports = {
        name
        for name in COMPONENT_REEXPORTS
        if name in name_set and exports.get(name) is not None and exports.get(name) != ".components"
    }
    extra = sorted(name_set - component_exports - allowed_reexports)
    if missing:
        errors.append(f"{components_module.__name__}.__all__ is missing root exports: {missing}")
    if extra:
        errors.append(
            f"{components_module.__name__}.__all__ contains names not exported from fastcharts: "
            f"{extra}"
        )

    for name in sorted(name_set):
        if not hasattr(components_module, name):
            errors.append(f"{components_module.__name__}.__all__ includes undefined name {name!r}")

    return errors


def validate_declarative_api_contract(
    pkg: ModuleType, components_module: ModuleType | None = None
) -> list[str]:
    """Ensure the Reflex-shaped composition API remains a named public contract."""
    errors: list[str] = []
    exports = getattr(pkg, "_EXPORTS", None)
    if not isinstance(exports, dict):
        return ["cannot validate declarative API because _EXPORTS is not a dict[str, str]"]

    public_names = set(_string_list(getattr(pkg, "__all__", None), "__all__", errors))

    if components_module is None:
        try:
            components_module = importlib.import_module(".components", pkg.__name__)
        except Exception as exc:
            return [f"cannot import fastcharts.components for declarative API validation: {exc!r}"]

    component_names = set(
        _string_list(
            getattr(components_module, "__all__", None),
            f"{components_module.__name__}.__all__",
            errors,
        )
    )

    for name in DECLARATIVE_API_EXPORTS:
        if name not in public_names:
            errors.append(f"declarative API export {name!r} is missing from fastcharts.__all__")
        if exports.get(name) != ".components":
            errors.append(
                f"declarative API export {name!r} must map to '.components', "
                f"got {exports.get(name)!r}"
            )
        if name not in component_names:
            errors.append(
                f"declarative API export {name!r} is missing from "
                f"{components_module.__name__}.__all__"
            )
        if not hasattr(components_module, name):
            errors.append(
                f"declarative API export {name!r} is undefined in {components_module.__name__}"
            )

    chart_class = getattr(components_module, "Chart", None)
    if chart_class is None:
        errors.append(f"{components_module.__name__}.Chart is missing")
        return errors
    for method in DECLARATIVE_CHART_READOUTS:
        value = getattr(chart_class, method, None)
        if not callable(value):
            errors.append(f"declarative Chart readout {method!r} must be callable")

    return errors


def validate_version_consistency(
    pkg: ModuleType, pyproject_path: Path = ROOT / "pyproject.toml"
) -> list[str]:
    """Ensure import-time ``__version__`` matches package metadata."""
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"cannot read project version from {pyproject_path}: {exc}"]

    project_version = str((data.get("project") or {}).get("version") or "").strip()
    public_version = getattr(pkg, "__version__", None)
    if not isinstance(public_version, str) or not public_version.strip():
        return [f"fastcharts.__version__ must be a non-empty string, got {public_version!r}"]
    if project_version != public_version:
        return [
            "fastcharts.__version__ must match pyproject.toml project.version: "
            f"{public_version!r} != {project_version!r}"
        ]
    return []


def validate_pep561_marker(
    marker_path: Path = ROOT / "python" / "fastcharts" / "py.typed",
) -> list[str]:
    """Ensure the source package advertises full-package typing support."""
    try:
        data = marker_path.read_bytes()
    except OSError as exc:
        return [f"missing PEP 561 marker {marker_path}: {exc}"]
    if data != b"":
        return [f"fastcharts py.typed must be an empty full-package PEP 561 marker; got {data!r}"]
    return []


def _loaded_import_budget_modules() -> list[str]:
    return sorted(
        name
        for name in sys.modules
        if name in HEAVY_THIRD_PARTY_IMPORTS or name.startswith("fastcharts.")
    )


def _format_eager_import_findings(label: str, eager: Any) -> list[str]:
    if not isinstance(eager, list) or any(not isinstance(name, str) for name in eager):
        return [f"{label} fresh import-budget probe returned invalid eager list: {eager!r}"]

    third_party = sorted(name for name in eager if name in HEAVY_THIRD_PARTY_IMPORTS)
    fastcharts_modules = sorted(name for name in eager if name.startswith("fastcharts."))
    other = sorted(
        name
        for name in eager
        if name not in HEAVY_THIRD_PARTY_IMPORTS and not name.startswith("fastcharts.")
    )

    errors: list[str] = []
    if third_party:
        errors.append(
            f"{label} import fastcharts eagerly loaded third-party modules before "
            f"chart API use: {third_party}"
        )
    if fastcharts_modules:
        errors.append(
            f"{label} import fastcharts eagerly loaded fastcharts submodules before "
            f"chart API use: {fastcharts_modules}"
        )
    if other:
        errors.append(
            f"{label} import fastcharts eagerly loaded unexpected modules before "
            f"chart API use: {other}"
        )
    return errors


def _format_fresh_public_metadata_findings(label: str, result: dict[str, Any]) -> list[str]:
    public_all = result.get("public_all")
    missing_from_dir = result.get("missing_from_dir")

    errors: list[str] = []
    if not isinstance(public_all, list) or any(not isinstance(name, str) for name in public_all):
        errors.append(f"{label} fresh import-budget probe returned invalid __all__: {public_all!r}")
    elif "__version__" not in public_all:
        errors.append(f"{label} fresh import-budget probe did not expose __version__ in __all__")

    if not isinstance(missing_from_dir, list) or any(
        not isinstance(name, str) for name in missing_from_dir
    ):
        errors.append(
            f"{label} fresh import-budget probe returned invalid dir() findings: "
            f"{missing_from_dir!r}"
        )
    elif missing_from_dir:
        errors.append(
            f"{label} dir(fastcharts) is missing public names after a fresh import: "
            f"{missing_from_dir}"
        )
    return errors


def check_fresh_import_budget(
    *,
    label: str = "default",
    extra_env: Optional[dict[str, str]] = None,
) -> list[str]:
    """Run the lazy-import probe in a fresh process.

    The in-process API coherence check intentionally imports every lazy export.
    Once that happens, `sys.modules` is no longer useful for proving package
    import stayed light. This subprocess keeps the release gate hermetic.
    """

    code = f"""
        import json
        import sys
        import time

        third_party_imports = {sorted(HEAVY_THIRD_PARTY_IMPORTS)!r}
        t0 = time.perf_counter()
        import fastcharts
        elapsed_ms = (time.perf_counter() - t0) * 1000
        public_all = list(fastcharts.__all__)
        dir_names = set(dir(fastcharts))
        missing_from_dir = sorted(name for name in public_all if name not in dir_names)
        eager = sorted(
            name
            for name in sys.modules
            if name in third_party_imports or name.startswith("fastcharts.")
        )
        print(json.dumps({{
            "elapsed_ms": elapsed_ms,
            "eager": eager,
            "missing_from_dir": missing_from_dir,
            "public_all": public_all,
            "version": fastcharts.__version__,
        }}))
    """
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    source_path = str(ROOT / "python")
    env["PYTHONPATH"] = (
        source_path if not env.get("PYTHONPATH") else source_path + os.pathsep + env["PYTHONPATH"]
    )
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        return [f"{label} fresh import-budget probe failed: {detail}"]

    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return [f"{label} fresh import-budget probe produced invalid JSON: {exc}: {proc.stdout!r}"]

    errors: list[str] = []
    errors.extend(_format_eager_import_findings(label, result.get("eager")))
    errors.extend(_format_fresh_public_metadata_findings(label, result))
    elapsed_ms = result.get("elapsed_ms")
    if not isinstance(elapsed_ms, int | float):
        errors.append(
            f"{label} fresh import-budget probe returned invalid elapsed_ms: {elapsed_ms!r}"
        )
    elif elapsed_ms > IMPORT_BUDGET_MS:
        errors.append(
            f"{label} import fastcharts took {elapsed_ms:.1f} ms; "
            f"budget is {IMPORT_BUDGET_MS:.0f} ms"
        )
    if not result.get("version"):
        errors.append(f"{label} fresh import-budget probe did not expose fastcharts.__version__")
    return errors


def check_all_fresh_import_budgets() -> list[str]:
    return check_fresh_import_budget(label="default")


def check_public_api(*, check_lazy_import: bool = True) -> list[str]:
    before = set(_loaded_import_budget_modules())
    pkg = importlib.import_module("fastcharts")
    after_import = set(_loaded_import_budget_modules())

    errors = check_all_fresh_import_budgets() if check_lazy_import else []
    errors.extend(validate_version_consistency(pkg))
    errors.extend(validate_pep561_marker())
    errors.extend(validate_public_api(pkg))
    errors.extend(validate_component_public_api(pkg))
    errors.extend(validate_declarative_api_contract(pkg))
    if check_lazy_import:
        eager = sorted(after_import - before)
        errors[:0] = _format_eager_import_findings("in-process", eager)

    # Exercise every advertised lazy export through getattr so stale mappings
    # fail as users would see them, not just by direct module imports.
    exports = getattr(pkg, "_EXPORTS", {})
    for name in sorted(exports):
        try:
            getattr(pkg, name)
        except Exception as exc:
            errors.append(f"getattr(fastcharts, {name!r}) failed: {exc!r}")

    return errors


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-lazy-import-check",
        action="store_true",
        help="only check export coherence, not import-time heaviness",
    )
    args = parser.parse_args(argv)

    errors = check_public_api(check_lazy_import=not args.skip_lazy_import_check)
    if errors:
        print("public API verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("public API verification OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
