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


def test_aggregating_kinds_build_zero_row_plans():
    """Every aggregating kind compiles a plan zero-row (the old exclusion is
    gone, and so are the synthetic columns that replaced it): under the
    core's structural_probe() mode the marks validate config and skip
    aggregation, with grouped/coordinate/weight channels recorded like any
    other."""
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


def test_structural_probe_still_fails_bad_aggregating_config():
    """No synthetic data does not mean no validation: configuration errors
    of the aggregating kinds fail the zero-row probe exactly like scatter's
    bad colormap does."""
    cases = [
        ("box orientation", (xy.box("v", orientation="diagonal"),)),
        ("violin bins", (xy.violin("v", bins=2),)),
        ("hexbin gridsize", (xy.hexbin("a", "b", gridsize=0),)),
        ("hexbin range", (xy.hexbin("a", "b", range=(0.0, 0.5)),)),
        ("hexbin mincnt", (xy.hexbin("a", "b", mincnt=-1),)),
        ("contour levels", (xy.contour("grid", levels=0),)),
        ("contour extend", (xy.contour("grid", extend="sideways"),)),
        ("heatmap colormap", (xy.heatmap("grid", colormap="virids"),)),
        ("stairs where", (xy.stairs("counts", where="diagonal"),)),
        ("ecdf bins", (xy.ecdf("v", bins=-1),)),
    ]
    for label, children in cases:
        with pytest.raises(ValueError, match=label.split(" ")[-1]):
            build_plan("chart", children, {})


def test_funnel_plan_records_all_channels_and_binds_real_rows():
    """An empty probe emits no funnel trace, but still discovers the key;
    row/type validation and transition-key encoding run when data binds."""
    plan = build_plan(
        "funnel_chart",
        (
            xy.funnel(
                "stage",
                "value",
                key="id",
                animation=xy.animation(match="key"),
            ),
        ),
        {},
    )
    assert plan.columns == ("stage", "value", "id")
    fig = plan.bind(
        {
            "stage": ["Visit", "Signup", "Pay"],
            "value": [100.0, 62.0, 21.0],
            "id": ["visit", "signup", "pay"],
        }
    ).figure()
    assert [trace.kind for trace in fig.traces] == ["funnel"]
    assert fig.traces[0].transition_keys is not None
    assert fig.traces[0].transition_keys.shape == (3, 2)


def test_funnel_plan_probe_still_fails_bad_config():
    with pytest.raises(ValueError, match="orientation"):
        build_plan(
            "funnel_chart",
            (xy.funnel("stage", "value", orientation="diagonal"),),
            {},
        )


def test_shared_columns_between_aggregating_and_zero_row_marks_probe():
    """The review's repro: stairs (values len k, edges len k+1) composed
    with a scatter that reads the same 'edges' column. Synthetic per-name
    shapes made the scatter probe see lengths 9 and 0; the all-empty
    structural probe has no lengths to disagree about, and the real mixed-
    length data binds."""
    plan = build_plan(
        "chart",
        (xy.stairs("counts", "edges"), xy.scatter("edges", "other")),
        {},
    )
    assert set(plan.columns) == {"counts", "edges", "other"}
    fig = plan.bind(
        {
            "counts": np.arange(8.0),
            "edges": np.arange(9.0),
            "other": np.arange(9.0) * 2.0,
        }
    ).figure()
    assert len(fig.traces) == 2


def test_hexbin_value_dependent_configs_probe_without_aggregating():
    """The review's other repro class: a range that excludes any invented
    points, a mincnt that filters them, or a maximal gridsize must not fail
    (or allocate) at page evaluation — those are data outcomes, computed
    only when real data binds."""
    for kwargs in (
        {"range": ((0.0, 0.5), (0.0, 0.5))},
        {"mincnt": 5},
        {"gridsize": 2048},
    ):
        plan = build_plan("hexbin_chart", (xy.hexbin("a", "b", **kwargs),), {})
        assert set(plan.columns) == {"a", "b"}
    # and the range case renders with real in-range data
    plan = build_plan("hexbin_chart", (xy.hexbin("a", "b", range=((0.0, 0.5), (0.0, 0.5))),), {})
    fig = plan.bind({"a": [0.1, 0.2, 0.3], "b": [0.1, 0.2, 0.3]}).figure()
    assert fig.traces[0].kind == "hexbin"


def test_shaped_and_zero_row_marks_compose_and_share_columns():
    plan = build_plan("chart", (xy.histogram("v"), xy.ecdf("v")), {})
    assert plan.columns == ("v",)


def test_named_callables_digest_and_lambdas_are_refused():
    """hexbin's reduce_C_function default (np.mean) content-addresses as its
    import path plus a code fingerprint, so identical trees agree across
    workers and different reducers disagree. A lambda has no stable name
    and cannot keep digests faithful; it is refused toward a module-level
    function or the hatch."""
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


def test_bound_methods_are_refused_as_plan_callables():
    """The review's repro: two bound reducers with different instance state
    used to serialize identically (module.qualname) — last-write-wins then
    made the first chart execute the second reducer. Instance state has no
    content address, so bound methods are refused outright."""

    class Quantile:
        def __init__(self, q: float) -> None:
            self.q = q

        def reduce(self, values: np.ndarray) -> float:
            return float(np.quantile(values, self.q))

    with pytest.raises(PlanError, match="bound method"):
        build_plan(
            "hexbin_chart",
            (xy.hexbin("a", "b", C="w", reduce_C_function=Quantile(0.5).reduce),),
            {},
        )


def test_callable_digest_follows_the_body_not_only_the_name():
    """A qualified name is identity, not content: editing a module-level
    reducer's body must change the digest (a rolling deployment otherwise
    executes two behaviors behind one address)."""
    import sys
    import types

    def module_reducer(body: str):
        module = types.ModuleType("plan_test_reducers")
        sys.modules["plan_test_reducers"] = module
        exec(  # noqa: S102 - building a same-qualname function pair for the pin
            f"import numpy as np\ndef reduce(values):\n    return {body}\n",
            module.__dict__,
        )
        return module.__dict__["reduce"]

    first = module_reducer("float(np.mean(values))")
    digest_one = build_plan(
        "hexbin_chart", (xy.hexbin("a", "b", C="w", reduce_C_function=first),), {}
    ).digest
    second = module_reducer("float(np.max(values))")  # same module.qualname
    digest_two = build_plan(
        "hexbin_chart", (xy.hexbin("a", "b", C="w", reduce_C_function=second),), {}
    ).digest
    assert digest_one != digest_two
    sys.modules.pop("plan_test_reducers", None)


def test_closures_are_refused_as_plan_callables():
    def make_reducer(q: float):
        def reduce(values: np.ndarray) -> float:
            return float(np.quantile(values, q))

        return reduce

    with pytest.raises(PlanError, match="stable qualified name"):
        build_plan(
            "hexbin_chart",
            (xy.hexbin("a", "b", C="w", reduce_C_function=make_reducer(0.5)),),
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
