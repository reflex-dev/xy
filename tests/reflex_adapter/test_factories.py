"""The data-bound chart factories: partition, schema checks, mounting."""

from __future__ import annotations

import inspect
from typing import TypedDict

import numpy as np
import pytest
import reflex as rx

import reflex_xy
import xy
from reflex_xy.factories import EVENT_TRIGGERS, FLAT_KINDS
from reflex_xy.handles import DataHandle


class FactorySchema(TypedDict):
    x: np.ndarray
    y: np.ndarray
    mag: np.ndarray


class FactoryDash(rx.State):
    points: int = 32
    handles: list[DataHandle[FactorySchema]] = []

    @reflex_xy.data
    def cloud(self) -> FactorySchema:
        xs = np.linspace(0.0, 1.0, self.points)
        return {"x": xs, "y": xs * 0.5, "mag": np.abs(xs)}

    @reflex_xy.data
    def untyped(self):
        return {"x": [1.0], "y": [2.0]}

    @rx.event
    def select(self, selection: dict):
        pass


def test_partition_table_is_the_public_contract():
    """The generated collision table (options doc §5.6 decision 2): the
    component level owns the reserved names; shadowed mark options get
    derived aliases — `stroke_width` when free and natural, `mark_<name>`
    otherwise. Failing here means the public flat-form surface moved."""
    base = {
        "mark_class_name": "class_name",
        "mark_opacity": "opacity",
        "mark_style": "style",
    }
    keyed = {**base, "mark_animation": "animation", "mark_key": "key"}
    aliases = {kind: FLAT_KINDS[kind].aliases for kind in sorted(FLAT_KINDS)}
    assert aliases == {
        "area_chart": keyed,
        "bar_chart": {**keyed, "mark_width": "width"},  # stroke_width is native
        "box_chart": {**base, "stroke_width": "width"},
        "column_chart": {**keyed, "mark_width": "width"},  # stroke_width is native
        "contour_chart": {**base, "stroke_width": "width"},
        "ecdf_chart": {**base, "stroke_width": "width"},
        "error_band_chart": keyed,
        "errorbar_chart": {**keyed, "stroke_width": "width"},
        "funnel_chart": keyed,
        "heatmap_chart": base,
        "hexbin_chart": base,
        "histogram_chart": base,
        "line_chart": {**keyed, "stroke_width": "width"},
        "scatter_chart": keyed,
        "segments_chart": {**base, "stroke_width": "width"},
        "stairs_chart": {**base, "stroke_width": "width"},
        "stem_chart": {**base, "stroke_width": "width"},
        "step_chart": {**base, "stroke_width": "width"},
        "triangle_mesh_chart": base,
        "violin_chart": {**base, "stroke_width": "width"},
    }


def test_private_mark_params_stay_off_the_public_surface(app_cwd):
    """The partition is signature-derived, so it inherits whatever xy's mark
    signatures carry — including the pyplot shim's private adapter knobs
    (`_artist_alpha`, `_marker_path`, …). Those are not documented options:
    accepting them would quietly widen the flat surface, and listing them as
    did-you-mean candidates would advertise it."""
    private = {name for name in inspect.signature(xy.scatter).parameters if name.startswith("_")}
    assert private  # the hazard is real, not hypothetical
    for kind in FLAT_KINDS.values():
        assert not {name for name in kind.mark_params if name.startswith("_")}
        assert not {name for name in kind.known if name.startswith("_")}
    with pytest.raises(TypeError, match="_artist_alpha"):
        reflex_xy.scatter_chart(data=FactoryDash.cloud, x="x", y="y", _artist_alpha=0.5)


def test_event_trigger_set_matches_the_component(app_cwd):
    """EVENT_TRIGGERS is derived by hand; pin it against the real component
    class so the two can never drift."""
    from reflex_xy.component import _component

    component_triggers = {
        name for name in _component().get_event_triggers() if name.startswith("on_")
    }
    assert component_triggers >= EVENT_TRIGGERS


def test_flat_factory_compiles_plan_and_data_props(app_cwd):
    comp = reflex_xy.scatter_chart(
        data=FactoryDash.cloud,
        x="x",
        y="y",
        color="mag",
        colormap="viridis",
        height="460px",
        on_select_end=FactoryDash.select,
    )
    rendered = str(comp)
    assert "plan:" in rendered
    assert "data:" in rendered
    assert "cloud" in rendered
    assert "onSelectEnd" in rendered
    assert "src" not in rendered


def test_flat_factory_validates_mark_config_at_compile(app_cwd):
    with pytest.raises(ValueError, match="colormap"):
        reflex_xy.scatter_chart(data=FactoryDash.cloud, x="x", y="y", colormap="virids")


def test_unknown_kwarg_near_a_known_name_suggests(app_cwd):
    with pytest.raises(TypeError, match="did you mean 'colormap'"):
        reflex_xy.scatter_chart(data=FactoryDash.cloud, x="x", y="y", colormapp="viridis")
    with pytest.raises(TypeError, match="did you mean 'on_select_end'"):
        reflex_xy.scatter_chart(
            data=FactoryDash.cloud, x="x", y="y", on_selection_end=FactoryDash.select
        )


def test_far_off_kwargs_error_and_point_at_style(app_cwd):
    """Strict top-level kwargs: a typo far from every known name errors at
    page evaluation instead of silently becoming CSS (the R8 hazard);
    explicit style={...} is the CSS route and still reaches the DOM."""
    with pytest.raises(TypeError, match=r"borderr_radus.*style=\{"):
        reflex_xy.scatter_chart(data=FactoryDash.cloud, x="x", y="y", borderr_radus="12px")
    comp = reflex_xy.scatter_chart(
        data=FactoryDash.cloud, x="x", y="y", style={"border_radius": "12px"}
    )
    assert "borderRadius" in {str(key) for key in comp.style}


def test_typed_schema_rejects_unknown_columns_at_compile(app_cwd):
    with pytest.raises(
        ValueError, match=r"unknown column 'timestamp'.*Available columns: mag, x, y"
    ):
        reflex_xy.scatter_chart(data=FactoryDash.cloud, x="timestamp", y="y")


def test_schema_check_reaches_foreach_item_vars(app_cwd):
    """R7 (foreach half): the element var of list[DataHandle[Schema]] keeps
    the schema, so column names are compile-checked inside loops."""
    good = rx.foreach(
        FactoryDash.handles,
        lambda handle: reflex_xy.scatter_chart(data=handle, x="x", y="y"),
    )
    good.render()

    with pytest.raises(ValueError, match="unknown column 'timestamp'"):
        rx.foreach(
            FactoryDash.handles,
            lambda handle: reflex_xy.scatter_chart(data=handle, x="timestamp", y="y"),
        ).render()


def test_untyped_data_var_skips_the_compile_column_check(app_cwd):
    comp = reflex_xy.scatter_chart(data=FactoryDash.untyped, x="anything", y="y")
    assert "plan:" in str(comp)


def test_wrong_var_and_raw_string_fail_at_compile(app_cwd):
    with pytest.raises(TypeError, match="data"):
        reflex_xy.scatter_chart(data=FactoryDash.points, x="x", y="y")
    with pytest.raises(TypeError, match="data="):
        reflex_xy.scatter_chart(data="xyd1|raw|token|string", x="x", y="y")


def test_static_tier_routes_concrete_columns_to_payload_asset(app_cwd, _fresh_registry):
    comp = reflex_xy.scatter_chart(
        data={"x": np.array([1.0, 2.0]), "y": np.array([2.0, 1.0])}, x="x", y="y"
    )
    rendered = str(comp)
    assert 'src:"/xy/' in rendered
    assert "plan:" not in rendered
    assert len(_fresh_registry) == 0  # static tier never touches the registry


def test_static_tier_bind_errors_name_both_sides(app_cwd):
    with pytest.raises(ValueError, match=r"plan binds column 'y'; data= produced \{x\}"):
        reflex_xy.scatter_chart(data={"x": [1.0]}, x="x", y="y")


def test_static_tier_refuses_kernel_events(app_cwd):
    with pytest.raises(ValueError, match=r"on_select_end.*static"):
        reflex_xy.scatter_chart(
            data={"x": [1.0], "y": [1.0]}, x="x", y="y", on_select_end=FactoryDash.select
        )


def test_missing_data_is_an_error(app_cwd):
    with pytest.raises(TypeError, match="data= is required"):
        reflex_xy.scatter_chart(x="x", y="y")


def test_live_charts_discover_tailwind_classes_from_the_probe(app_cwd):
    """The zero-row probe figure's class inventory reaches the JSX scan
    literal automatically — live plan charts no longer need the manual
    tailwind_classes= inventory (the Phase-2 'bonus' in the plan doc)."""
    rendered = str(
        reflex_xy.scatter_chart(
            data=FactoryDash.cloud,
            x="x",
            y="y",
            legend=xy.legend(class_name="max-h-24 overflow-y-auto"),
            class_names={"title": "text-base font-semibold"},
        )
    )
    assert "tailwindClassTokens" in rendered
    assert "max-h-24 overflow-y-auto" in rendered
    assert "text-base font-semibold" in rendered


def test_chrome_kwargs_type_dispatch(app_cwd):
    comp = reflex_xy.scatter_chart(
        data=FactoryDash.cloud,
        x="x",
        y="y",
        x_axis=xy.x_axis(label="sigma"),
        legend=True,
    )
    assert "plan:" in str(comp)
    # a string is the mark's axis-id option, and an undeclared id fails the
    # probe exactly like xy itself would at .figure()
    with pytest.raises(ValueError, match="axis"):
        reflex_xy.scatter_chart(data=FactoryDash.cloud, x="x", y="y", y_axis="y2")
    with pytest.raises(TypeError, match="axis node"):
        reflex_xy.scatter_chart(data=FactoryDash.cloud, x="x", y="y", x_axis=42)


def test_line_stroke_width_alias_and_bar_mark_width(app_cwd):
    line = reflex_xy.line_chart(data=FactoryDash.cloud, x="x", y="y", stroke_width=3.0)
    assert "plan:" in str(line)
    bar = reflex_xy.bar_chart(data=FactoryDash.cloud, x="x", y="y", mark_width=0.5)
    assert "plan:" in str(bar)
    hist = reflex_xy.histogram_chart(data=FactoryDash.cloud, values="mag", bins=32)
    assert "plan:" in str(hist)


def test_composed_chart_consumes_xy_nodes(app_cwd):
    comp = reflex_xy.chart(
        xy.scatter(x="x", y="y", color="mag", colormap="viridis"),
        xy.line(x="x", y="y", width=2),
        xy.x_axis(label="t"),
        data=FactoryDash.cloud,
        height="300px",
    )
    assert "plan:" in str(comp)


def test_composed_chart_checks_schema_across_all_marks(app_cwd):
    with pytest.raises(ValueError, match="unknown column 'trend'"):
        reflex_xy.chart(
            xy.scatter(x="x", y="y"),
            xy.line(x="x", y="trend"),
            data=FactoryDash.cloud,
        )


def test_cond_between_two_composed_charts_validates_both(app_cwd):
    """rx.cond builds both branches eagerly (R4), so both plans compile."""
    comp = rx.cond(
        FactoryDash.points > 10,
        reflex_xy.scatter_chart(data=FactoryDash.cloud, x="x", y="y"),
        reflex_xy.line_chart(data=FactoryDash.cloud, x="x", y="y"),
    )
    assert "plan:" in str(comp.render())

    with pytest.raises(ValueError, match="unknown column"):
        rx.cond(
            FactoryDash.points > 10,
            reflex_xy.scatter_chart(data=FactoryDash.cloud, x="x", y="y"),
            reflex_xy.line_chart(data=FactoryDash.cloud, x="x", y="bogus"),
        )


def test_component_tier_still_reachable_through_chart(app_cwd):
    """chart() keeps dispatching the escape hatch and static tiers."""
    static = reflex_xy.chart(xy.line_chart(xy.line([0.0, 1.0], [1.0, 2.0])))
    assert 'src:"/xy/' in str(static)
    live = reflex_xy.chart(figure=reflex_xy.FigureHandle("tok"))
    assert "figure" in str(live)
    with pytest.raises(TypeError, match="data="):
        reflex_xy.chart(figure=reflex_xy.FigureHandle("tok"), data=FactoryDash.cloud)


def test_curated_reexports_are_the_xy_constructors():
    """`reflex_xy.scatter` *is* `xy.scatter` (zero duplication), and a
    hallucinated constructor dies at import against the explicit map."""
    assert reflex_xy.scatter is xy.scatter
    assert reflex_xy.funnel is xy.funnel
    assert reflex_xy.x_axis is xy.x_axis
    assert reflex_xy.legend is xy.legend
    assert reflex_xy.vline is xy.vline
    with pytest.raises(AttributeError, match="polar_scatter"):
        reflex_xy.polar_scatter  # noqa: B018 - the access is the assertion


def test_every_flat_kind_compiles_a_plan(app_cwd):
    """The signature-derived factories cover every standalone mark kind —
    all compiled from zero-row columns under the structural probe."""
    from reflex_xy.factories import FLAT_KINDS

    calls = {
        "scatter_chart": dict(x="x", y="y"),
        "line_chart": dict(x="x", y="y"),
        "histogram_chart": dict(values="x"),
        "bar_chart": dict(x="x", y="y"),
        "area_chart": dict(x="x", y="y"),
        "step_chart": dict(x="x", y="y"),
        "stem_chart": dict(x="x", y="y"),
        "column_chart": dict(x="x", y="y"),
        "errorbar_chart": dict(x="x", y="y", yerr="mag"),
        "error_band_chart": dict(x="x", lower="y", upper="mag"),
        "segments_chart": dict(x0="x", y0="y", x1="x", y1="mag"),
        "funnel_chart": dict(stage="x", value="y", mark_key="mag"),
        "box_chart": dict(values="mag"),
        "violin_chart": dict(values="mag"),
        "ecdf_chart": dict(values="mag"),
        "hexbin_chart": dict(x="x", y="y"),
        "contour_chart": dict(z="mag"),
        "heatmap_chart": dict(z="mag"),
        "stairs_chart": dict(values="x", edges="y"),
        "triangle_mesh_chart": dict(x0="x", y0="y", x1="mag", y1="x", x2="y", y2="mag"),
    }
    assert set(calls) == set(FLAT_KINDS)
    for kind, channels in calls.items():
        comp = getattr(reflex_xy, kind)(data=FactoryDash.cloud, **channels)
        assert "plan:" in str(comp), kind


def test_flat_funnel_preserves_core_chart_defaults(app_cwd, monkeypatch):
    """The Reflex flat factory must retain funnel's semantic chrome rather
    than compiling it as a generic one-mark chart."""
    import reflex_xy.factories as factories

    monkeypatch.setattr(factories, "_mount", lambda plan, _data, _kwargs: plan)
    plan = reflex_xy.funnel_chart(data=FactoryDash.cloud, stage="x", value="y")
    fig = plan.bind({"x": ["Visit", "Signup"], "y": [100.0, 62.0]}).figure()
    spec, _ = fig.build_payload()
    assert spec["x_axis"]["style"]["axis_color"] == "#00000000"
    assert spec["y_axis"]["reverse"] is True
    assert spec["show_legend"] is False

    horizontal = reflex_xy.funnel_chart(
        data=FactoryDash.cloud,
        stage="x",
        value="y",
        orientation="horizontal",
    )
    horizontal_fig = horizontal.bind({"x": ["Visit", "Signup"], "y": [100.0, 62.0]}).figure()
    horizontal_spec, _ = horizontal_fig.build_payload()
    assert horizontal_spec["y_axis"]["style"]["axis_color"] == "#00000000"
    assert horizontal_spec["x_axis"].get("reverse", False) is False


def test_aggregating_marks_compile_through_the_structural_probe(app_cwd):
    """Aggregating marks are first-class in the plan tier: the structural
    probe uses empty columns, skips aggregation, and still validates config
    at compile like every other kind."""
    comp = reflex_xy.chart(xy.box("mag"), xy.ecdf("mag"), data=FactoryDash.cloud)
    assert "plan:" in str(comp)
    with pytest.raises(ValueError, match="colormap"):
        reflex_xy.heatmap_chart(data=FactoryDash.cloud, z="mag", colormap="virids")
    with pytest.raises(ValueError, match="unknown column 'reading'"):
        reflex_xy.violin_chart(data=FactoryDash.cloud, values="reading")
