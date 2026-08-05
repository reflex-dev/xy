"""Chart plans: compile-time validation, content addressing, binding."""

from __future__ import annotations

import numpy as np
import pytest

import xy
from reflex_xy.plan import (
    PLAN_VERSION,
    PlanBindError,
    PlanError,
    PlanMissError,
    build_plan,
    plan_of,
    require_plan,
)


def scatter_plan(**mark_options):
    return build_plan(
        "scatter_chart",
        (xy.scatter("x", "y", color="mag", **mark_options), xy.x_axis(label="sigma")),
        {"title": "cloud"},
    )


def test_plan_records_probed_columns_in_resolution_order():
    plan = scatter_plan()
    assert plan.columns == ("x", "y", "mag")


def test_digest_is_stable_across_identical_builds():
    """Content addressing: separately constructed identical trees agree, so
    every worker evaluating the same page derives the same digest (X4)."""
    assert scatter_plan().digest == scatter_plan().digest
    assert scatter_plan().digest != scatter_plan(opacity=0.5).digest


def test_digest_golden_pins_the_plan_format():
    """plan_version is part of the serialization: accidental format churn
    shows up here as a digest change. An *intentional* format change bumps
    PLAN_VERSION and re-records this golden (old digests are content
    addresses — stale subscribers resync, nothing migrates)."""
    assert PLAN_VERSION == 1
    plan = build_plan("scatter_chart", (xy.scatter("x", "y"),), {})
    assert plan.digest == "b7d0b4245b686130e37d"


def test_probe_fires_the_full_validation_gate():
    with pytest.raises(ValueError, match="colormap"):
        scatter_plan(colormap="virids")
    with pytest.raises(ValueError, match="symbol"):
        scatter_plan(symbol="marsian")
    # unresolved axis-id references are figure-compile errors too (X2)
    with pytest.raises(ValueError, match="axis"):
        build_plan("scatter_chart", (xy.scatter("x", "y", y_axis="y2"),), {})


def test_shaped_probe_table_is_the_recorded_contract():
    """The synthetic-channel table (spec: reflex-integration.md "Kind
    coverage") is a recorded decision, §28 spirit: extending a kind means
    recording its validator's minimal shape here, never a silent guess.
    Keys name the Mark storage each factory param lands on (x/y fields or
    props entries)."""
    from reflex_xy.plan import _SYNTHETIC_CHANNELS

    assert {kind: sorted(channels) for kind, channels in _SYNTHETIC_CHANNELS.items()} == {
        "box": ["props.group", "props.x", "x"],
        "violin": ["props.group", "props.x", "x"],
        "hexbin": ["props.C", "x", "y"],
        "contour": ["props.z", "x", "y"],
        "heatmap": ["props.z", "x", "y"],
        "stairs": ["x", "y"],
        "ecdf": ["x"],
    }


def test_aggregating_kinds_build_plans_with_shaped_probes():
    """Every aggregating kind compiles a plan (the old exclusion is gone),
    with grouped/coordinate/weight channels recorded like any other."""
    cases = [
        ("box_chart", (xy.box("v", group="g"),), {"v", "g"}),
        ("violin_chart", (xy.violin("v"),), {"v"}),
        ("hexbin_chart", (xy.hexbin("a", "b", C="w"),), {"a", "b", "w"}),
        ("contour_chart", (xy.contour("grid", x="xs", y="ys"),), {"grid", "xs", "ys"}),
        ("heatmap_chart", (xy.heatmap("grid"),), {"grid"}),
        ("stairs_chart", (xy.stairs("counts", "edges"),), {"counts", "edges"}),
        ("ecdf_chart", (xy.ecdf("v"),), {"v"}),
    ]
    for kind, children, expected in cases:
        plan = build_plan(kind, children, {})
        assert set(plan.columns) == expected, kind


def test_shaped_and_zero_row_marks_compose_and_share_columns():
    plan = build_plan("chart", (xy.histogram("v"), xy.ecdf("v")), {})
    assert plan.columns == ("v",)


def test_named_callables_digest_and_lambdas_are_refused():
    """hexbin's reduce_C_function default (np.mean) has a stable import
    path — that path is its content address, so identical trees still agree
    across workers. A lambda has no stable name and cannot keep digests
    faithful; it is refused toward a module-level function or the hatch."""
    hexbin_plan = build_plan("hexbin_chart", (xy.hexbin("a", "b", C="w"),), {})
    again = build_plan("hexbin_chart", (xy.hexbin("a", "b", C="w"),), {})
    assert hexbin_plan.digest == again.digest
    reduced = build_plan(
        "hexbin_chart", (xy.hexbin("a", "b", C="w", reduce_C_function=np.median),), {}
    )
    assert reduced.digest != hexbin_plan.digest
    with pytest.raises(PlanError, match="stable qualified name"):
        build_plan(
            "hexbin_chart",
            (xy.hexbin("a", "b", C="w", reduce_C_function=lambda values: values.max()),),
            {},
        )


def test_plans_refuse_concrete_arrays():
    with pytest.raises(PlanError, match="data-free"):
        build_plan("scatter_chart", (xy.scatter(np.array([1.0]), np.array([2.0])),), {})


def test_plans_refuse_per_mark_data():
    with pytest.raises(PlanError, match="per-mark data="):
        build_plan("scatter_chart", (xy.scatter("x", "y", data={"x": [], "y": []}),), {})


def test_plans_refuse_render_components():
    with pytest.raises(PlanError, match="render"):
        build_plan(
            "scatter_chart",
            (xy.scatter("x", "y"), xy.legend(render=object())),
            {},
        )


def test_plan_is_a_snapshot_immune_to_later_node_mutation():
    """The registered plan holds a deep copy of what was hashed: mutating a
    reused mark node or the chart props afterwards must not change binding
    behavior behind an unchanged digest/columns record."""
    mark = xy.scatter("x", "y", color="mag")
    props = {"title": "cloud"}
    plan = build_plan("scatter_chart", (mark,), props)
    assert plan.columns == ("x", "y", "mag")

    mark.props["color"] = "sneaky"  # node reused and mutated by page code
    props["title"] = "renamed"
    assert plan.children[0] is not mark
    assert plan.children[0].props["color"] == "mag"
    assert plan.chart_props == {"title": "cloud"}
    # binding still resolves the snapshot's channels, not the mutated node's
    fig = plan.bind({"x": [1.0], "y": [2.0], "mag": [3.0]}).figure()
    assert fig.traces[0].n_points == 1


def test_bind_produces_fresh_figures_per_call():
    """X3: Chart.figure() memoizes, so bind() must mint a fresh Chart —
    two binds with different columns give independent figures."""
    plan = build_plan("scatter_chart", (xy.scatter("x", "y"),), {})
    small = plan.bind({"x": [1.0], "y": [2.0]}).figure()
    large = plan.bind({"x": [1.0, 2.0, 3.0], "y": [2.0, 3.0, 4.0]}).figure()
    assert small is not large
    assert small.traces[0].n_points == 1
    assert large.traces[0].n_points == 3


def test_bind_error_names_both_sides():
    plan = scatter_plan()
    with pytest.raises(
        PlanBindError, match=r"plan binds column 'mag'; Dash.cloud produced \{x, y\}"
    ):
        plan.bind({"x": [1.0], "y": [2.0]}, source="Dash.cloud")


def test_probe_collects_the_tailwind_inventory():
    plan = build_plan(
        "scatter_chart",
        (xy.scatter("x", "y"), xy.legend(class_name="max-h-24 overflow-y-auto")),
        {"class_name": "rounded-xl"},
    )
    assert "rounded-xl" in plan.tailwind_classes
    assert "max-h-24" in plan.tailwind_classes


def test_registry_lookup_and_miss():
    plan = scatter_plan()
    assert plan_of(plan.digest) is plan
    assert plan_of("feedfacefeedfacefeed") is None
    with pytest.raises(PlanMissError, match="feedfacefeedfacefeed"):
        require_plan("feedfacefeedfacefeed")
