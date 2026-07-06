from __future__ import annotations

import inspect
from os import PathLike
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

import numpy as np

import fastcharts as fc
import fastcharts.components as components
import fastcharts.figure as figure_module

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
)
CHART_FACTORIES = (
    "scatter_chart",
    "line_chart",
    "area_chart",
    "histogram_chart",
    "bar_chart",
    "column_chart",
    "heatmap_chart",
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
    "to_png",
    "memory_report",
)


def test_source_package_carries_pep561_marker() -> None:
    marker = ROOT / "python" / "fastcharts" / "py.typed"

    assert marker.is_file()
    assert marker.read_bytes() == b""


def test_component_types_are_lazy_public_root_exports() -> None:
    for name in ("Component", "Mark", "Axis", "Legend", "Chart"):
        assert name in fc.__all__
        assert getattr(fc, name) is getattr(components, name)


def test_components_module_all_matches_root_component_exports() -> None:
    component_exports = {
        name for name, module_name in fc._EXPORTS.items() if module_name == ".components"
    }

    assert set(components.__all__) == component_exports
    assert len(components.__all__) == len(set(components.__all__))
    for name in components.__all__:
        assert hasattr(components, name), name


def test_public_factories_are_typed_root_exports() -> None:
    for name in (
        *MARK_FACTORIES,
        "x_axis",
        "y_axis",
        "legend",
        *CHART_FACTORIES,
    ):
        root_fn = getattr(fc, name)
        component_fn = getattr(components, name)
        assert name in fc.__all__
        assert root_fn is component_fn
        assert inspect.signature(root_fn) == inspect.signature(component_fn)
        assert get_type_hints(root_fn) == get_type_hints(component_fn)


def test_public_component_factories_have_typed_signatures() -> None:
    expected_returns = {
        **{name: components.Mark for name in MARK_FACTORIES},
        "x_axis": components.Axis,
        "y_axis": components.Axis,
        "legend": components.Legend,
        **{name: components.Chart for name in CHART_FACTORIES},
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

    memory_report_return = get_type_hints(components.Chart.memory_report)["return"]
    assert get_origin(memory_report_return) is dict
    assert get_args(memory_report_return) == (str, Any)


def test_chart_and_figure_html_export_types_stay_in_sync() -> None:
    figure_hints = get_type_hints(figure_module.Figure.to_html)
    chart_hints = get_type_hints(components.Chart.to_html)

    assert chart_hints["return"] is str
    assert chart_hints == figure_hints

    path_hint = chart_hints["path"]
    path_args = get_args(path_hint)
    assert str in path_args
    assert type(None) in path_args
    assert any(get_origin(arg) is PathLike for arg in path_args)


def test_chart_and_figure_png_export_types_stay_in_sync() -> None:
    figure_hints = get_type_hints(figure_module.Figure.to_png)
    chart_hints = get_type_hints(components.Chart.to_png)

    assert chart_hints["return"] is bytes
    assert chart_hints == figure_hints

    for key in ("path", "width", "height", "chromium"):
        args = get_args(chart_hints[key])
        assert type(None) in args, key
    assert str in get_args(chart_hints["path"])
    assert chart_hints["scale"] is float
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
