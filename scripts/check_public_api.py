#!/usr/bin/env python3
"""Verify the lazy public API surface is coherent.

`xy.__init__` intentionally hand-maintains two things:

- `__all__`, the names users can import from `xy`
- `_EXPORTS`, the lazy export map that keeps `import xy` lightweight

That is a good shape for import-time performance, but it is easy to forget one
side when adding a chart family. This stdlib-only check catches drift before a
release or CI green build.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import inspect
import json
import os
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Optional, get_type_hints

ROOT = Path(__file__).resolve().parents[1]
IMPORT_BUDGET_MS = 200.0
HEAVY_THIRD_PARTY_IMPORTS = {
    "anywidget",
    "numpy",
    "traitlets",
}
HEAVY_XY_IMPORTS = {
    "xy.channels",
    "xy.channel",
    "xy.columns",
    "xy.components",
    "xy._figure",
    "xy.interaction",
    "xy.kernels",
    "xy.lod",
    "xy.marks",
    "xy._native",
    "xy.widget",
}
HEAVY_IMPORTS = HEAVY_THIRD_PARTY_IMPORTS | HEAVY_XY_IMPORTS
COMPONENT_REEXPORTS = {"CHART_DOM_SLOTS"}
CHROME_RETURN_TYPES = {"Colorbar", "Interaction", "Legend", "Modebar", "Theme", "Tooltip"}
SUPPORT_RETURN_TYPES = {"Animation", "ExportConfig", "FacetChart", "Spring"}
SPECIAL_PUBLIC_CHART_METHODS = {"_repr_html_"}
SPECIAL_PUBLIC_SELECTION_METHODS = {"__len__"}
EXPERIMENTAL_PUBLIC_EXPORTS: tuple[str, ...] = ()
DEPRECATED_PUBLIC_EXPORTS: tuple[str, ...] = ()
PRIVATE_PUBLIC_EXPORTS: tuple[str, ...] = ()
CHART_METHOD_DOC = ROOT / "docs" / "api-reference" / "figure-methods.md"
SELECTION_METHOD_DOC = ROOT / "docs" / "api-reference" / "events-and-callbacks.md"


@dataclass(frozen=True)
class PublicApiInventory:
    """Machine-readable inventory of the supported public composition API."""

    component_reexports: tuple[str, ...]
    component_types: tuple[str, ...]
    mark_factories: tuple[str, ...]
    annotation_factories: tuple[str, ...]
    axis_factories: tuple[str, ...]
    chrome_factories: tuple[str, ...]
    chart_factories: tuple[str, ...]
    support_factories: tuple[str, ...]
    chart_methods: tuple[str, ...]
    selection_methods: tuple[str, ...]
    experimental_exports: tuple[str, ...] = EXPERIMENTAL_PUBLIC_EXPORTS
    deprecated_exports: tuple[str, ...] = DEPRECATED_PUBLIC_EXPORTS
    private_exports: tuple[str, ...] = PRIVATE_PUBLIC_EXPORTS

    @property
    def component_factories(self) -> tuple[str, ...]:
        return (
            *self.mark_factories,
            *self.annotation_factories,
            *self.axis_factories,
            *self.chrome_factories,
            *self.chart_factories,
            *self.support_factories,
        )

    @property
    def declarative_exports(self) -> tuple[str, ...]:
        return (
            *self.component_types,
            *self.component_factories,
        )

    @property
    def classified_component_exports(self) -> tuple[str, ...]:
        return (
            *self.component_reexports,
            *self.declarative_exports,
            *self.experimental_exports,
            *self.deprecated_exports,
            *self.private_exports,
        )


PUBLIC_API_MANIFEST = PublicApiInventory(
    component_reexports=("CHART_DOM_SLOTS",),
    component_types=(
        "Animation",
        "Annotation",
        "Axis",
        "Chart",
        "Colorbar",
        "Component",
        "ExportConfig",
        "FacetChart",
        "Interaction",
        "Legend",
        "Mark",
        "Modebar",
        "Spring",
        "Theme",
        "Tooltip",
    ),
    mark_factories=(
        "area",
        "bar",
        "box",
        "column",
        "contour",
        "ecdf",
        "error_band",
        "errorbar",
        "heatmap",
        "hexbin",
        "hist",
        "histogram",
        "line",
        "mark",
        "ribbon",
        "sankey",
        "scatter",
        "segments",
        "stairs",
        "stem",
        "step",
        "triangle_mesh",
        "violin",
    ),
    annotation_factories=(
        "arrow",
        "callout",
        "hline",
        "label",
        "marker",
        "text",
        "threshold",
        "threshold_zone",
        "vline",
        "x_band",
        "y_band",
    ),
    axis_factories=("r_axis", "theta_axis", "x_axis", "y_axis"),
    chrome_factories=("colorbar", "interaction_config", "legend", "modebar", "theme", "tooltip"),
    chart_factories=(
        "area_chart",
        "bar_chart",
        "box_chart",
        "chart",
        "column_chart",
        "contour_chart",
        "ecdf_chart",
        "error_band_chart",
        "errorbar_chart",
        "heatmap_chart",
        "hexbin_chart",
        "histogram_chart",
        "line_chart",
        "pie_chart",
        "polar_bar_chart",
        "polar_chart",
        "radar_chart",
        "sankey_chart",
        "scatter_chart",
        "segments_chart",
        "stairs_chart",
        "stem_chart",
        "step_chart",
        "triangle_mesh_chart",
        "violin_chart",
        "wind_rose",
    ),
    support_factories=("animation", "export_config", "facet_chart", "spring"),
    chart_methods=(
        "figure",
        "chrome_components",
        "reflex_components",
        "widget",
        "show",
        "set_view",
        "reset_view",
        "select",
        "clear_selection",
        "view_state",
        "to_html",
        "html",
        "_repr_html_",
        "to_svg",
        "to_png",
        "to_image",
        "write_image",
        "memory_report",
        "append",
        "pick",
        "select_range",
    ),
    selection_methods=("index", "__len__", "xy", "rows"),
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
        errors.append(f"dir(xy) is missing public names: {dir_missing}")

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
            return [f"cannot import xy.components for public API validation: {exc!r}"]

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
            f"{components_module.__name__}.__all__ contains names not exported from xy: {extra}"
        )

    for name in sorted(name_set):
        if not hasattr(components_module, name):
            errors.append(f"{components_module.__name__}.__all__ includes undefined name {name!r}")

    return errors


def _return_type_name(value: Any) -> str | None:
    try:
        return_type = get_type_hints(value).get("return")
    except Exception:
        return None
    return getattr(return_type, "__name__", None)


def _component_factory_categories(components_module: ModuleType) -> dict[str, list[str]]:
    categories = {
        "mark_factories": [],
        "annotation_factories": [],
        "axis_factories": [],
        "chrome_factories": [],
        "chart_factories": [],
        "support_factories": [],
    }
    for name in getattr(components_module, "__all__", ()):
        if name in COMPONENT_REEXPORTS:
            continue
        value = getattr(components_module, name, None)
        if not inspect.isfunction(value):
            continue
        return_name = _return_type_name(value)
        if return_name == "Mark":
            categories["mark_factories"].append(name)
        elif return_name == "Annotation":
            categories["annotation_factories"].append(name)
        elif return_name == "Axis":
            categories["axis_factories"].append(name)
        elif return_name == "Chart":
            categories["chart_factories"].append(name)
        elif return_name in CHROME_RETURN_TYPES:
            categories["chrome_factories"].append(name)
        elif return_name in SUPPORT_RETURN_TYPES:
            categories["support_factories"].append(name)
    return categories


def _public_methods(
    cls: type[Any],
    *,
    special_public_methods: set[str],
) -> tuple[str, ...]:
    methods: list[str] = []
    for name, value in cls.__dict__.items():
        if name == "__init__":
            continue
        if not callable(value) and not isinstance(value, property):
            continue
        if name.startswith("_") and name not in special_public_methods:
            continue
        methods.append(name)
    return tuple(methods)


def build_public_api_inventory(
    pkg: ModuleType,
    components_module: ModuleType | None = None,
) -> PublicApiInventory:
    """Build the public API inventory from exported objects and annotations."""
    if components_module is None:
        components_module = importlib.import_module(".components", pkg.__name__)

    component_names = tuple(getattr(components_module, "__all__", ()))
    categories = _component_factory_categories(components_module)
    component_types = tuple(
        name
        for name in component_names
        if name not in COMPONENT_REEXPORTS
        and inspect.isclass(getattr(components_module, name, None))
    )
    chart_methods = _public_methods(
        components_module.Chart,
        special_public_methods=SPECIAL_PUBLIC_CHART_METHODS,
    )
    figure_module = importlib.import_module("._figure", pkg.__name__)
    selection_methods = _public_methods(
        figure_module.Selection,
        special_public_methods=SPECIAL_PUBLIC_SELECTION_METHODS,
    )
    return PublicApiInventory(
        component_reexports=tuple(name for name in component_names if name in COMPONENT_REEXPORTS),
        component_types=component_types,
        mark_factories=tuple(categories["mark_factories"]),
        annotation_factories=tuple(categories["annotation_factories"]),
        axis_factories=tuple(categories["axis_factories"]),
        chrome_factories=tuple(categories["chrome_factories"]),
        chart_factories=tuple(categories["chart_factories"]),
        support_factories=tuple(categories["support_factories"]),
        chart_methods=chart_methods,
        selection_methods=selection_methods,
    )


def validate_public_api_inventory(
    inventory: PublicApiInventory,
    components_module: ModuleType,
) -> list[str]:
    """Ensure every component export is explicitly classified in the inventory."""
    errors: list[str] = []
    component_names = set(
        _string_list(
            getattr(components_module, "__all__", None),
            f"{components_module.__name__}.__all__",
            errors,
        )
    )
    classified = set(inventory.classified_component_exports)
    missing = sorted(component_names - classified)
    stale = sorted(classified - component_names)
    if missing:
        errors.append(f"component public exports are unclassified: {missing}")
    if stale:
        errors.append(f"public API inventory classifies non-exported names: {stale}")
    return errors


def validate_public_api_manifest(
    inventory: PublicApiInventory,
    manifest: PublicApiInventory = PUBLIC_API_MANIFEST,
) -> list[str]:
    """Ensure discovery neither adds nor silently removes supported names."""
    errors: list[str] = []
    fields = (
        "component_reexports",
        "component_types",
        "mark_factories",
        "annotation_factories",
        "axis_factories",
        "chrome_factories",
        "chart_factories",
        "support_factories",
        "chart_methods",
        "selection_methods",
    )
    for field_name in fields:
        expected = set(getattr(manifest, field_name))
        actual = set(getattr(inventory, field_name))
        missing = sorted(expected - actual)
        added = sorted(actual - expected)
        if missing:
            errors.append(f"public API manifest names missing from discovery ({field_name}): {missing}")
        if added:
            errors.append(f"public API discovery contains unmanifested names ({field_name}): {added}")
    return errors


def _has_doc_reference(text: str, name: str, *, receiver: str | None = None) -> bool:
    tokens = [f"`{name}`", f"`{name}()`", f"`{name}(`"]
    if receiver is not None:
        tokens.extend(
            (
                f"`{receiver}.{name}()`",
                f"`{receiver}.{name}(`",
                f"{receiver}.{name}(",
            )
        )
    return any(token in text for token in tokens) or re.search(
        rf"(?<![A-Za-z0-9_]){re.escape(name)}\s*\(", text
    ) is not None


def validate_docs_inventory(
    inventory: PublicApiInventory,
    *,
    chart_doc: Path = CHART_METHOD_DOC,
    selection_doc: Path = SELECTION_METHOD_DOC,
) -> list[str]:
    """Ensure public methods have API reference coverage."""
    errors: list[str] = []
    try:
        chart_text = chart_doc.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read Chart API docs {chart_doc}: {exc}"]
    try:
        selection_text = selection_doc.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read Selection API docs {selection_doc}: {exc}"]

    for method in inventory.chart_methods:
        if not _has_doc_reference(chart_text, method, receiver="chart"):
            errors.append(f"Chart public method {method!r} is missing from {chart_doc}")
    selection_aliases = {"__len__": "len(selection)"}
    for method in inventory.selection_methods:
        token = selection_aliases.get(method)
        if token is not None:
            if token not in selection_text:
                errors.append(f"Selection public method {method!r} is missing from {selection_doc}")
        elif not _has_doc_reference(selection_text, method):
            errors.append(f"Selection public method {method!r} is missing from {selection_doc}")
    return errors


def validate_declarative_api_contract(
    pkg: ModuleType,
    components_module: ModuleType | None = None,
    *,
    manifest: PublicApiInventory | None = None,
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
            return [f"cannot import xy.components for declarative API validation: {exc!r}"]

    component_names = set(
        _string_list(
            getattr(components_module, "__all__", None),
            f"{components_module.__name__}.__all__",
            errors,
        )
    )
    if errors:
        return errors

    chart_class = getattr(components_module, "Chart", None)
    if chart_class is None:
        errors.append(f"{components_module.__name__}.Chart is missing")
        return errors

    inventory = build_public_api_inventory(pkg, components_module)
    errors.extend(validate_public_api_inventory(inventory, components_module))
    if manifest is not None:
        errors.extend(validate_public_api_manifest(inventory, manifest))

    for name in inventory.declarative_exports:
        if name not in public_names:
            errors.append(f"declarative API export {name!r} is missing from xy.__all__")
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

    for method in inventory.chart_methods:
        value = getattr(chart_class, method, None)
        if not callable(value):
            errors.append(f"declarative Chart readout {method!r} must be callable")
    errors.extend(validate_docs_inventory(inventory))

    return errors


def validate_version_consistency(pkg: ModuleType, distribution: str = "xy") -> list[str]:
    """Ensure import-time ``__version__`` matches installed package metadata.

    pyproject holds no version to compare against — it is derived from the git
    tag at build time — so installed metadata is the reference. The check that
    remains is worth keeping: `xy.__version__` is resolved lazily through
    ``__getattr__``, and this is what catches it resolving to something other
    than the version pip actually installed (a stale editable install shadowing
    a wheel, say), rather than merely to *some* non-empty string.
    """
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as distribution_version

    try:
        installed_version = distribution_version(distribution)
    except PackageNotFoundError:
        return [
            f"distribution {distribution!r} is not installed, so xy.__version__ "
            "cannot be checked — run this against an installed package"
        ]

    public_version = getattr(pkg, "__version__", None)
    if not isinstance(public_version, str) or not public_version.strip():
        return [f"xy.__version__ must be a non-empty string, got {public_version!r}"]
    if installed_version != public_version:
        return [
            f"xy.__version__ must match the installed {distribution} distribution "
            f"metadata: {public_version!r} != {installed_version!r}"
        ]
    return []


def validate_pep561_marker(
    marker_path: Path = ROOT / "python" / "xy" / "py.typed",
) -> list[str]:
    """Ensure the source package advertises full-package typing support."""
    try:
        data = marker_path.read_bytes()
    except OSError as exc:
        return [f"missing PEP 561 marker {marker_path}: {exc}"]
    if data != b"":
        return [f"xy py.typed must be an empty full-package PEP 561 marker; got {data!r}"]
    return []


def validate_static_typing_surface(
    pkg: ModuleType,
    init_path: Path = ROOT / "python" / "xy" / "__init__.py",
) -> list[str]:
    """Ensure every lazy root export also has a static declaration.

    Runtime consumers resolve root names through ``__getattr__``.  A type
    checker cannot infer the per-name types hidden behind that dynamic hook, so
    each public name must also be imported under ``TYPE_CHECKING`` (or, for a
    lazily materialized scalar such as ``__version__``, explicitly annotated).
    """
    errors: list[str] = []
    public_names = set(_string_list(getattr(pkg, "__all__", None), "__all__", errors))

    try:
        tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    except (OSError, SyntaxError) as exc:
        return [*errors, f"cannot inspect static typing surface in {init_path}: {exc}"]

    declared: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            declared.add(statement.target.id)
            continue
        if not (
            isinstance(statement, ast.If)
            and isinstance(statement.test, ast.Name)
            and statement.test.id == "TYPE_CHECKING"
        ):
            continue
        for child in statement.body:
            if isinstance(child, ast.ImportFrom):
                declared.update(
                    alias.asname or alias.name for alias in child.names if alias.name != "*"
                )
            elif isinstance(child, ast.Import):
                declared.update(
                    alias.asname or alias.name.split(".", 1)[0] for alias in child.names
                )

    missing = sorted(public_names - declared)
    if missing:
        errors.append(
            f"xy public names have no static TYPE_CHECKING import or annotation: {missing}"
        )
    return errors


def _loaded_import_budget_modules() -> list[str]:
    return sorted(
        name for name in sys.modules if name in HEAVY_THIRD_PARTY_IMPORTS or name.startswith("xy.")
    )


def _format_eager_import_findings(label: str, eager: Any) -> list[str]:
    if not isinstance(eager, list) or any(not isinstance(name, str) for name in eager):
        return [f"{label} fresh import-budget probe returned invalid eager list: {eager!r}"]

    third_party = sorted(name for name in eager if name in HEAVY_THIRD_PARTY_IMPORTS)
    xy_modules = sorted(name for name in eager if name.startswith("xy."))
    other = sorted(
        name
        for name in eager
        if name not in HEAVY_THIRD_PARTY_IMPORTS and not name.startswith("xy.")
    )

    errors: list[str] = []
    if third_party:
        errors.append(
            f"{label} import xy eagerly loaded third-party modules before "
            f"chart API use: {third_party}"
        )
    if xy_modules:
        errors.append(
            f"{label} import xy eagerly loaded xy submodules before chart API use: {xy_modules}"
        )
    if other:
        errors.append(
            f"{label} import xy eagerly loaded unexpected modules before chart API use: {other}"
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
            f"{label} dir(xy) is missing public names after a fresh import: {missing_from_dir}"
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
        import xy
        elapsed_ms = (time.perf_counter() - t0) * 1000
        public_all = list(xy.__all__)
        dir_names = set(dir(xy))
        missing_from_dir = sorted(name for name in public_all if name not in dir_names)
        eager = sorted(
            name
            for name in sys.modules
            if name in third_party_imports or name.startswith("xy.")
        )
        print(json.dumps({{
            "elapsed_ms": elapsed_ms,
            "eager": eager,
            "missing_from_dir": missing_from_dir,
            "public_all": public_all,
            "version": xy.__version__,
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
            f"{label} import xy took {elapsed_ms:.1f} ms; budget is {IMPORT_BUDGET_MS:.0f} ms"
        )
    if not result.get("version"):
        errors.append(f"{label} fresh import-budget probe did not expose xy.__version__")
    return errors


def check_all_fresh_import_budgets() -> list[str]:
    return check_fresh_import_budget(label="default")


def check_public_api(*, check_lazy_import: bool = True) -> list[str]:
    before = set(_loaded_import_budget_modules())
    pkg = importlib.import_module("xy")
    after_import = set(_loaded_import_budget_modules())

    errors = check_all_fresh_import_budgets() if check_lazy_import else []
    errors.extend(validate_version_consistency(pkg))
    errors.extend(validate_pep561_marker())
    errors.extend(validate_static_typing_surface(pkg))
    errors.extend(validate_public_api(pkg))
    errors.extend(validate_component_public_api(pkg))
    errors.extend(validate_declarative_api_contract(pkg, manifest=PUBLIC_API_MANIFEST))
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
            errors.append(f"getattr(xy, {name!r}) failed: {exc!r}")

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
