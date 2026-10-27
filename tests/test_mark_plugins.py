"""A mark plugin composes built-in marks and gets the engine for free (§24).

The containment argument is the whole design: a plugin returns `Mark` objects
and never touches the `Figure`, the trace list, or the column store, so its
traces cannot differ from hand-written ones in decimation, picking, hover, a11y,
or any export path. These tests hold that argument rather than merely checking
that the registry accepts a callable.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

import xy


def _hilo_plugin(name: str = "hilo") -> xy.MarkPlugin:
    def calc(columns):
        return {**columns, "mid": (columns["low"] + columns["high"]) / 2.0}

    def build(ctx):
        return [
            xy.segments(
                x0=ctx.columns["t"],
                x1=ctx.columns["t"],
                y0=ctx.columns["low"],
                y1=ctx.columns["high"],
                name=ctx.name,
                style=ctx.style,
            ),
            xy.scatter(
                x=ctx.columns["t"],
                y=ctx.columns["mid"],
                size=ctx.options.get("mid_size", 6),
            ),
        ]

    return xy.MarkPlugin(name=name, columns=("t", "low", "high"), calc=calc, build=build)


@pytest.fixture
def hilo():
    plugin = xy.register_mark(_hilo_plugin())
    try:
        yield plugin
    finally:
        xy.unregister_mark(plugin.name)


def test_a_plugin_mark_compiles_to_ordinary_traces(hilo) -> None:
    chart = xy.chart(
        xy.mark("hilo", t=[0.0, 1.0, 2.0], low=[1.0, 2.0, 1.5], high=[3.0, 4.0, 3.5], name="band")
    )
    fig = chart.figure()

    # One plugin mark, two primitives, and nothing about them marks them as
    # second-class: they are the same kinds the built-in constructors produce.
    assert [t.kind for t in fig.traces] == ["segments", "scatter"]
    spec, _ = fig.build_payload()
    assert {t["kind"] for t in spec["traces"]} == {"segments", "scatter"}


def test_calc_runs_before_build_and_its_columns_are_what_build_sees(hilo) -> None:
    fig = xy.chart(xy.mark("hilo", t=[0.0, 1.0], low=[1.0, 3.0], high=[3.0, 5.0])).figure()
    scatter = next(t for t in fig.traces if t.kind == "scatter")
    assert list(scatter.y.values) == [2.0, 4.0]


def test_declared_columns_resolve_from_data_like_a_built_in_mark(hilo) -> None:
    frame = {"t": [0.0, 1.0], "lo": [1.0, 2.0], "hi": [3.0, 4.0]}
    fig = xy.chart(xy.mark("hilo", t="t", low="lo", high="hi", data=frame)).figure()
    assert [t.kind for t in fig.traces] == ["segments", "scatter"]

    with pytest.raises(ValueError, match=r"hilo.low column 'nope' not found"):
        xy.chart(xy.mark("hilo", t="t", low="nope", high="hi", data=frame)).figure()


def test_undeclared_keywords_reach_the_plugin_as_options(hilo) -> None:
    fig = xy.chart(
        xy.mark("hilo", t=[0.0, 1.0], low=[1.0, 2.0], high=[3.0, 4.0], mid_size=14)
    ).figure()
    scatter = next(t for t in fig.traces if t.kind == "scatter")
    assert scatter.size_ch is not None and scatter.size_ch.constant == pytest.approx(14.0)


def test_plugin_traces_reach_every_renderer(hilo) -> None:
    fig = xy.chart(
        xy.mark(
            "hilo",
            t=[0.0, 1.0, 2.0],
            low=[1.0, 2.0, 1.5],
            high=[3.0, 4.0, 3.5],
            style={"stroke": "#ff0000"},
        )
    ).figure()

    assert "#ff0000" in fig.to_svg()
    from xy import _raster

    image = _raster.render_raster(*fig.build_payload(), scale=1)
    assert np.any(image[:, :, 0] > image[:, :, 2])


def test_a_plugin_mark_honors_named_axes(hilo) -> None:
    fig = xy.chart(
        xy.mark(
            "hilo",
            t=[0.0, 1.0],
            low=[1.0, 2.0],
            high=[3.0, 4.0],
            y_axis="y2",
        ),
        xy.y_axis(id="y2"),
    ).figure()
    assert all(t.y_axis == "y2" for t in fig.traces)


def test_the_registry_refuses_to_shadow_or_silently_replace() -> None:
    with pytest.raises(ValueError, match="built-in mark kind"):
        xy.register_mark(xy.MarkPlugin(name="scatter", build=lambda ctx: []))

    first = xy.register_mark(_hilo_plugin("twice"))
    try:
        with pytest.raises(ValueError, match="already registered"):
            xy.register_mark(_hilo_plugin("twice"))
        assert xy.register_mark(_hilo_plugin("twice"), replace=True) is not first
    finally:
        xy.unregister_mark("twice")

    with pytest.raises(ValueError, match="must be an identifier"):
        xy.register_mark(xy.MarkPlugin(name="not a name", build=lambda ctx: []))


def test_registered_marks_lists_only_contributed_kinds(hilo) -> None:
    assert "hilo" in xy.registered_marks()
    assert "scatter" not in xy.registered_marks()
    xy.unregister_mark("hilo")
    assert "hilo" not in xy.registered_marks()
    xy.register_mark(_hilo_plugin())


def test_an_unknown_plugin_name_fails_at_construction_not_at_compile() -> None:
    with pytest.raises(ValueError, match="unknown mark plugin 'nope'"):
        xy.mark("nope", x=[0.0])


def test_build_must_return_built_in_marks() -> None:
    def bad_type(ctx):
        return "not marks"

    def nested(ctx):
        return [xy.mark("inner", x=[0.0])]

    xy.register_mark(xy.MarkPlugin(name="badtype", build=bad_type))
    xy.register_mark(xy.MarkPlugin(name="inner", build=lambda ctx: []))
    xy.register_mark(xy.MarkPlugin(name="nested", build=nested))
    try:
        with pytest.raises(TypeError, match="must return a sequence of marks"):
            xy.chart(xy.mark("badtype")).figure()
        # One level only: plugins compose built-ins, not each other.
        with pytest.raises(TypeError, match=re.escape("plugins compose built-in marks only")):
            xy.chart(xy.mark("nested")).figure()
    finally:
        for name in ("badtype", "inner", "nested"):
            xy.unregister_mark(name)


def test_calc_must_return_a_mapping() -> None:
    xy.register_mark(
        xy.MarkPlugin(
            name="badcalc", columns=("x",), calc=lambda cols: [1, 2], build=lambda ctx: []
        )
    )
    try:
        with pytest.raises(TypeError, match="calc must return a mapping"):
            xy.chart(xy.mark("badcalc", x=[0.0])).figure()
    finally:
        xy.unregister_mark("badcalc")


def test_a_plugin_cannot_reach_the_figure(hilo) -> None:
    seen = {}

    def build(ctx):
        seen["ctx"] = ctx
        return [xy.line(x=ctx.columns["t"], y=ctx.columns["low"])]

    xy.register_mark(xy.MarkPlugin(name="probe", columns=("t", "low"), build=build))
    try:
        xy.chart(xy.mark("probe", t=[0.0, 1.0], low=[1.0, 2.0])).figure()
    finally:
        xy.unregister_mark("probe")

    ctx = seen["ctx"]
    assert set(vars(ctx)) == {"columns", "options", "name", "style", "class_name"}
    assert not any(hasattr(ctx, attr) for attr in ("figure", "traces", "store", "fig"))


def test_a_plugin_cannot_claim_a_name_that_xy_mark_binds_itself() -> None:
    # `xy.mark(name=...)` is the series label, so a plugin column called `name`
    # could never be passed — the value would bind to the parameter and the
    # column would resolve to None. Reject the schema, not the call site.
    for reserved in ("name", "style", "data", "x_axis", "key"):
        with pytest.raises(ValueError, match=re.escape("xy.mark() binds itself")):
            xy.register_mark(
                xy.MarkPlugin(name="clashing", columns=(reserved,), build=lambda ctx: [])
            )
    assert "clashing" not in xy.registered_marks()


def test_declared_columns_reach_calc_as_canonical_f64(hilo) -> None:
    # Canonical data is CPU-side f64 (§27). A float32 input must widen before
    # `calc` runs, or the arithmetic rounds at f32 and hands the loss to a
    # built-in mark that stores f64 anyway.
    seen = {}

    def build(ctx):
        seen["dtypes"] = {k: v.dtype for k, v in ctx.columns.items()}
        return [xy.line(x=ctx.columns["t"], y=ctx.columns["low"])]

    xy.register_mark(xy.MarkPlugin(name="dtypes", columns=("t", "low"), build=build))
    try:
        xy.chart(
            xy.mark(
                "dtypes",
                t=np.array([0.0, 1.0], dtype=np.float32),
                low=np.array([1, 2], dtype=np.int16),
            )
        ).figure()
    finally:
        xy.unregister_mark("dtypes")

    assert all(dtype == np.float64 for dtype in seen["dtypes"].values())
