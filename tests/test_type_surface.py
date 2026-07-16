from __future__ import annotations

import inspect
from os import PathLike
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

import numpy as np
import pytest

import xy as fc
import xy._figure as figure_module
import xy.components as components
from xy.export import Engine

ROOT = Path(__file__).resolve().parents[1]

MARK_FACTORIES = (
    "scatter",
    "line",
    "area",
    "histogram",
    "hist",
    "bar",
    "column",
    "heatmap",
    "error_band",
    "errorbar",
    "box",
    "violin",
    "ecdf",
    "hexbin",
    "contour",
    "step",
    "stairs",
    "stem",
    "segments",
    "triangle_mesh",
)
ANNOTATION_FACTORIES = (
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
CHART_FACTORIES = (
    "chart",
    "scatter_chart",
    "line_chart",
    "area_chart",
    "histogram_chart",
    "bar_chart",
    "column_chart",
    "heatmap_chart",
    "error_band_chart",
    "errorbar_chart",
    "box_chart",
    "violin_chart",
    "ecdf_chart",
    "hexbin_chart",
    "contour_chart",
    "step_chart",
    "stairs_chart",
    "stem_chart",
    "segments_chart",
    "triangle_mesh_chart",
)
CHROME_FACTORIES = (
    "legend",
    "tooltip",
    "colorbar",
    "modebar",
    "theme",
    "interaction_config",
)
CHART_READOUTS = (
    "figure",
    "widget",
    "show",
    "to_html",
    "html",
    "_repr_html_",
    "to_svg",
    "to_png",
    "memory_report",
    "chrome_components",
    "reflex_components",
    "append",
    "pick",
    "select_range",
)
FIGURE_BUILDERS = (
    "line",
    "scatter",
    "area",
    "histogram",
    "hist",
    "bar",
    "column",
    "heatmap",
    "error_band",
    "errorbar",
    "box",
    "violin",
    "ecdf",
    "hexbin",
    "contour",
    "step",
    "stairs",
    "stem",
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
FIGURE_READOUTS = (
    "build_payload",
    "x_range",
    "y_range",
    "density_view",
    "pick",
    "select_range",
    "to_shipped_indices",
    "decimate_view",
    "widget",
    "show",
    "to_html",
    "html",
    "_repr_html_",
    "to_png",
    "memory_report",
)


def test_source_package_carries_pep561_marker() -> None:
    marker = ROOT / "python" / "xy" / "py.typed"

    assert marker.is_file()
    assert marker.read_bytes() == b""


def test_component_types_are_lazy_public_root_exports() -> None:
    for name in (
        "CHART_DOM_SLOTS",
        "Component",
        "FacetChart",
        "Mark",
        "Colorbar",
        "Annotation",
        "Axis",
        "Interaction",
        "Legend",
        "Chart",
    ):
        assert name in fc.__all__
        assert getattr(fc, name) is getattr(components, name)


def test_export_engine_is_lazy_public_enum() -> None:
    assert "Engine" in fc.__all__
    assert fc.Engine is Engine
    assert tuple(Engine) == (Engine.default, Engine.chromium)


def test_chart_dom_slots_are_public_styling_contract() -> None:
    expected = (
        "root",
        "title",
        "chrome",
        "canvas",
        "labels",
        "legend",
        "legend_item",
        "legend_swatch",
        "colorbar",
        "colorbar_bar",
        "colorbar_tick",
        "colorbar_title",
        "tooltip",
        "modebar",
        "modebar_button",
        "selection",
        "crosshair_x",
        "crosshair_y",
        "badge",
        "badge_item",
        "tick_label",
        "axis_title",
        "annotation_label",
    )

    assert fc.CHART_DOM_SLOTS is components.CHART_DOM_SLOTS
    assert expected == components.CHART_DOM_SLOTS
    assert len(components.CHART_DOM_SLOTS) == len(set(components.CHART_DOM_SLOTS))
    assert all(slot == slot.lower() and " " not in slot for slot in components.CHART_DOM_SLOTS)

    design = (ROOT / "docs" / "engineering" / "design" / "reflex-shaped-api.md").read_text(
        encoding="utf-8"
    )
    for slot in components.CHART_DOM_SLOTS:
        assert f"`{slot}`" in design


def test_chart_class_names_are_limited_to_public_dom_slots() -> None:
    chart = fc.chart(
        fc.scatter(x=[1.0], y=[2.0]),
        class_names={slot: f"slot-{slot}" for slot in fc.CHART_DOM_SLOTS},
    )

    assert chart.class_names["legend"] == "slot-legend"
    with pytest.raises(ValueError, match="unknown slot"):
        fc.chart(fc.scatter(x=[1.0], y=[2.0]), class_names={"plot": "not-a-slot"})


def test_components_module_all_matches_root_component_exports() -> None:
    component_exports = {
        name for name, module_name in fc._EXPORTS.items() if module_name == ".components"
    }
    component_reexports = {"CHART_DOM_SLOTS"}

    assert set(components.__all__) == component_exports | component_reexports
    assert len(components.__all__) == len(set(components.__all__))
    for name in components.__all__:
        assert hasattr(components, name), name


def test_public_factories_are_typed_root_exports() -> None:
    for name in (
        *MARK_FACTORIES,
        *ANNOTATION_FACTORIES,
        "x_axis",
        "y_axis",
        *CHROME_FACTORIES,
        *CHART_FACTORIES,
    ):
        root_fn = getattr(fc, name)
        component_fn = getattr(components, name)
        assert name in fc.__all__
        assert root_fn is component_fn
        assert inspect.signature(root_fn) == inspect.signature(component_fn)
        assert get_type_hints(root_fn) == get_type_hints(component_fn)


def test_composition_alpha_contract_is_explicitly_exported() -> None:
    contract = {
        *MARK_FACTORIES,
        *ANNOTATION_FACTORIES,
        *CHART_FACTORIES,
        *CHROME_FACTORIES,
        "x_axis",
        "y_axis",
    }

    for name in sorted(contract):
        assert name in fc.__all__
        assert name in components.__all__
        assert fc._EXPORTS[name] == ".components"
        assert getattr(fc, name) is getattr(components, name)

    for method in CHART_READOUTS:
        assert hasattr(components.Chart, method)
        assert callable(getattr(components.Chart, method))


def test_public_component_factories_have_typed_signatures() -> None:
    expected_returns = {
        **{name: components.Mark for name in MARK_FACTORIES},
        **{name: components.Annotation for name in ANNOTATION_FACTORIES},
        "x_axis": components.Axis,
        "y_axis": components.Axis,
        "legend": components.Legend,
        "tooltip": components.Tooltip,
        "colorbar": components.Colorbar,
        "modebar": components.Modebar,
        "theme": components.Theme,
        "interaction_config": components.Interaction,
        **{name: components.Chart for name in CHART_FACTORIES},
        "facet_chart": components.FacetChart,
    }
    for name, expected_return in expected_returns.items():
        fn = getattr(components, name)
        hints = get_type_hints(fn)
        signature = inspect.signature(fn)
        assert hints.get("return") is expected_return, name
        for param_name, param in signature.parameters.items():
            assert param.annotation is not inspect.Signature.empty, f"{name}.{param_name}"


def test_mark_factory_kinds_are_registered_with_typed_appliers() -> None:
    factory_kinds = {getattr(components, name)().kind for name in MARK_FACTORIES}
    applier_kinds = set(components._MARK_APPLIERS)

    assert factory_kinds == applier_kinds
    for kind, applier in components._MARK_APPLIERS.items():
        signature = inspect.signature(applier)
        hints = get_type_hints(applier)
        assert tuple(signature.parameters) == ("fig", "m", "data"), kind
        assert hints["fig"] is figure_module.Figure, kind
        assert hints["m"] is components.Mark, kind
        assert hints["data"] is Any, kind
        assert hints["return"] is type(None), kind


def test_annotation_factory_kinds_are_registered_with_typed_appliers() -> None:
    factory_kinds = set()
    for name in ANNOTATION_FACTORIES:
        if name == "arrow":
            annotation = components.arrow(0.0, 1.0, 2.0, 3.0)
        elif name == "callout":
            annotation = components.callout(0.0, 1.0, "label")
        elif name == "label":
            annotation = components.label(0.0, 1.0, "label")
        elif name == "text":
            annotation = components.text(0.0, 1.0, "label")
        elif name == "marker":
            annotation = components.marker(0.0, 1.0)
        elif name == "threshold_zone":
            annotation = components.threshold_zone(0.0, 1.0)
        elif name == "threshold":
            annotation = components.threshold(1.0)
        elif name.endswith("_band"):
            annotation = getattr(components, name)(0.0, 1.0)
        else:
            annotation = getattr(components, name)(0.0)
        factory_kinds.add(annotation.kind)

    assert factory_kinds == set(components._ANNOTATION_APPLIERS)
    for kind, applier in components._ANNOTATION_APPLIERS.items():
        signature = inspect.signature(applier)
        hints = get_type_hints(applier)
        assert tuple(signature.parameters) == ("fig", "annotation"), kind
        assert hints["fig"] is figure_module.Figure, kind
        assert hints["annotation"] is components.Annotation, kind
        assert hints["return"] is type(None), kind


def test_chart_factories_construct_named_lazy_charts() -> None:
    for name in CHART_FACTORIES:
        chart = getattr(components, name)()
        assert isinstance(chart, components.Chart), name
        assert chart.kind == name
        assert chart.children == ()
        assert chart._figure is None
        assert chart._widget is None


def test_component_dataclass_and_chart_method_types_are_specific() -> None:
    mark_hints = get_type_hints(components.Mark)
    props_hint = mark_hints["props"]
    assert get_origin(props_hint) is dict
    assert get_args(props_hint) == (str, Any)

    assert get_type_hints(components.Chart.figure)["return"] is figure_module.Figure
    assert get_type_hints(components.Chart.widget)["return"] is Any
    assert get_type_hints(components.Chart.show)["return"] is Any

    memory_report_return = get_type_hints(components.Chart.memory_report)["return"]
    assert get_origin(memory_report_return) is dict
    assert get_args(memory_report_return) == (str, Any)

    assert get_type_hints(components.Chart.append)["return"] is type(None)
    pick_return = get_type_hints(components.Chart.pick)["return"]
    assert type(None) in get_args(pick_return)  # Optional[dict[str, Any]]
    assert get_type_hints(components.Chart.select_range)["return"] is figure_module.Selection

    for method in ("chrome_components", "reflex_components"):
        return_hint = get_type_hints(getattr(components.Chart, method))["return"]
        assert get_origin(return_hint) is dict
        assert get_args(return_hint) == (str, Any)


def test_chart_and_figure_html_export_types_stay_in_sync() -> None:
    figure_hints = get_type_hints(figure_module.Figure.to_html)
    chart_hints = get_type_hints(components.Chart.to_html)
    figure_alias_hints = get_type_hints(figure_module.Figure.html)
    chart_alias_hints = get_type_hints(components.Chart.html)

    assert chart_hints["return"] is str
    assert chart_hints == figure_hints
    assert chart_alias_hints == figure_alias_hints == figure_hints

    path_hint = chart_hints["path"]
    path_args = get_args(path_hint)
    assert str in path_args
    assert type(None) in path_args
    assert any(get_origin(arg) is PathLike for arg in path_args)

    figure_repr_hints = get_type_hints(figure_module.Figure._repr_html_)
    chart_repr_hints = get_type_hints(components.Chart._repr_html_)
    assert figure_repr_hints == chart_repr_hints == {"return": str}


def test_chart_and_figure_png_export_types_stay_in_sync() -> None:
    figure_hints = get_type_hints(figure_module.Figure.to_png)
    chart_hints = get_type_hints(components.Chart.to_png)

    assert chart_hints["return"] is bytes
    assert chart_hints == figure_hints

    for key in ("path", "width", "height", "custom_css"):
        args = get_args(chart_hints[key])
        assert type(None) in args, key
    assert str in get_args(chart_hints["path"])
    assert str in get_args(chart_hints["custom_css"])
    assert chart_hints["scale"] is float
    assert chart_hints["engine"] is Engine
    assert chart_hints["sandbox"] is bool


def test_public_figure_methods_have_typed_signatures() -> None:
    for name in (*FIGURE_BUILDERS, *FIGURE_READOUTS):
        fn = getattr(figure_module.Figure, name)
        hints = get_type_hints(fn)
        signature = inspect.signature(fn)
        assert hints.get("return") is not None, name
        for param_name, param in signature.parameters.items():
            if param_name == "self":
                continue
            assert param.annotation is not inspect.Signature.empty, f"Figure.{name}.{param_name}"

    for name in FIGURE_BUILDERS:
        assert get_type_hints(getattr(figure_module.Figure, name))["return"] is figure_module.Figure

    assert get_type_hints(figure_module.Figure.to_html)["return"] is str
    assert get_type_hints(figure_module.Figure.to_png)["return"] is bytes
    build_payload_return = get_type_hints(figure_module.Figure.build_payload)["return"]
    assert get_origin(build_payload_return) is tuple
    assert get_args(build_payload_return) == (dict[str, Any], bytes)


def test_selection_callback_payload_types_are_specific() -> None:
    init_hints = get_type_hints(figure_module.Selection.__init__)
    assert init_hints["figure"] is figure_module.Figure
    assert get_origin(init_hints["per_trace"]) is dict
    assert get_args(init_hints["per_trace"]) == (int, np.ndarray)
    assert init_hints["return"] is type(None)

    index_getter = figure_module.Selection.index.fget
    assert index_getter is not None
    assert get_type_hints(index_getter)["return"] is np.ndarray
    assert get_type_hints(figure_module.Selection.__len__)["return"] is int

    xy_return = get_type_hints(figure_module.Selection.xy)["return"]
    assert get_origin(xy_return) is tuple
    assert get_args(xy_return) == (np.ndarray, np.ndarray)
