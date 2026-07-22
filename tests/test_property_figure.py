"""Property-based tests for every public figure builder.

Hypothesis drives the complete public-builder catalog through inputs that must
succeed and through classified invalid inputs that must fail cleanly.  The core
builders additionally keep their broad hostile-array exploration — NaN, ±inf,
huge/tiny magnitudes, empty, constant, unsorted, and mismatched lengths.  The
tests check the invariants the wire contract promises rather than specific
values:

  P1  build_payload either succeeds or raises ValueError/TypeError — never a
      crash class (IndexError/ZeroDivisionError/FloatingPointError/...).
  P2  the spec is plain JSON (no numpy scalars leak, §29 "no JSON numbers"
      means buffers, but the spec itself must serialize).
  P3  every column reference in the spec is a valid index into `columns`,
      and every (byte_offset, len) window lies inside the blob.
  P4  geometry buffers never carry non-finite values (§19 — nothing
      non-finite reaches a vertex buffer).
  P5  autorange is finite and covers the finite data (padded), per the
      per-kind `range_for` contract (e.g. histogram bars, heatmap extents).
  P6  every trace records its tier; reduced traces stay screen-bounded.
  P7  determinism: building twice yields byte-identical blob + equal spec
      (the anti-shimmer guarantee starts kernel-side).
  P8  a late exception after trace insertion restores the exact seeded figure
      state, including columns/caches and LOD interaction bookkeeping.

Hypothesis is a required development dependency.  Missing it is a broken test
environment, not a reason to silently skip this contract.
"""

from __future__ import annotations

import dataclasses
import json
import math
import struct
import weakref
from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from xy import interaction
from xy._figure import Figure

# Bounded so the whole module stays CI-cheap (< ~30s).
COMMON = settings(max_examples=60, deadline=None)

finite_floats = st.floats(allow_nan=False, allow_infinity=False, min_value=-1e12, max_value=1e12)
hostile_floats = st.one_of(
    finite_floats,
    st.just(float("nan")),
    st.just(float("inf")),
    st.just(float("-inf")),
    st.just(0.0),
    st.just(-0.0),
    st.just(1e300),
    st.just(5e-324),
)


def hostile_array(min_size=0, max_size=200):
    return st.lists(hostile_floats, min_size=min_size, max_size=max_size).map(
        lambda v: np.asarray(v, dtype=np.float64)
    )


ACCEPTABLE = (ValueError, TypeError)

PUBLIC_BUILDERS = (
    "line",
    "area",
    "scatter",
    "histogram",
    "hist",
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
    "bar",
    "column",
    "heatmap",
)

VALID_COMMON = settings(max_examples=12, deadline=None)
INVALID_COMMON = settings(max_examples=8, deadline=None)
safe_floats = st.floats(
    min_value=-100.0,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
    allow_subnormal=False,
)


@dataclass(frozen=True)
class Invocation:
    """One generated call against a named public builder."""

    args: tuple[Any, ...]
    kwargs: dict[str, Any]


@dataclass(frozen=True)
class InvalidInvocation(Invocation):
    """A generated rejection with an explicit validation classification."""

    category: str
    match: str


def _draw_values(draw: st.DrawFn, n: int) -> np.ndarray:
    return np.asarray(
        draw(st.lists(safe_floats, min_size=n, max_size=n)),
        dtype=np.float64,
    )


@st.composite
def _valid_invocation(draw: st.DrawFn, builder: str) -> Invocation:
    """Constrained data that is valid by construction for one builder."""
    n = draw(st.integers(min_value=2, max_value=10))
    values = _draw_values(draw, n)
    offset = draw(st.floats(min_value=-10.0, max_value=10.0, allow_nan=False))
    spacing = draw(st.floats(min_value=0.25, max_value=4.0, allow_nan=False))
    x = offset + spacing * np.arange(n, dtype=np.float64)
    if draw(st.booleans()):
        x = x[::-1].copy()  # line-like builders must accept and sort valid x

    if builder == "line":
        return Invocation((x, values), {"curve": draw(st.sampled_from(("linear", "smooth")))})
    if builder == "area":
        base = draw(safe_floats) if draw(st.booleans()) else values - np.abs(_draw_values(draw, n))
        return Invocation((x, values), {"base": base})
    if builder == "scatter":
        sizes = np.abs(_draw_values(draw, n)) + 0.25
        colors = _draw_values(draw, n)
        return Invocation(
            (x, values),
            {
                "color": colors,
                "size": sizes,
                "density": draw(st.sampled_from((None, False, True))),
            },
        )
    if builder in {"histogram", "hist"}:
        return Invocation(
            (values,),
            {
                "bins": draw(st.integers(min_value=1, max_value=12)),
                "density": draw(st.booleans()),
                "cumulative": draw(st.booleans()),
            },
        )
    if builder == "error_band":
        extent = np.abs(_draw_values(draw, n)) + 0.01
        return Invocation((x, values - extent, values + extent), {})
    if builder == "errorbar":
        extent = np.abs(_draw_values(draw, n))
        axis = draw(st.sampled_from(("xerr", "yerr")))
        return Invocation((x, values), {axis: extent})
    if builder in {"box", "violin"}:
        groups = np.asarray([f"group-{index % 3}" for index in range(n)], dtype=object)
        kwargs: dict[str, Any] = {
            "x": groups,
            "orientation": draw(st.sampled_from(("vertical", "horizontal"))),
        }
        if builder == "box":
            kwargs["show_outliers"] = draw(st.booleans())
        else:
            kwargs["bins"] = draw(st.integers(min_value=4, max_value=24))
        return Invocation((values,), kwargs)
    if builder == "ecdf":
        bins = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=12)))
        return Invocation((values,), {"bins": bins})
    if builder == "hexbin":
        hx = np.linspace(-1.0, 1.0, n, dtype=np.float64)
        hy = hx**2 + np.linspace(0.0, 0.5, n, dtype=np.float64)
        return Invocation(
            (hx, hy),
            {
                "gridsize": draw(st.integers(min_value=2, max_value=8)),
                "range": ((-1.25, 1.25), (-0.25, 1.75)),
                "bins": draw(st.sampled_from(("count", "log"))),
            },
        )
    if builder == "contour":
        rows = draw(st.integers(min_value=2, max_value=5))
        cols = draw(st.integers(min_value=2, max_value=5))
        row = np.linspace(0.0, 1.0, rows, dtype=np.float64)[:, None]
        col = np.linspace(0.0, 1.0, cols, dtype=np.float64)[None, :]
        z = row + col + draw(st.floats(min_value=-5.0, max_value=5.0, allow_nan=False))
        level = float((np.min(z) + np.max(z)) / 2.0)
        return Invocation((z,), {"levels": np.asarray([level]), "filled": draw(st.booleans())})
    if builder == "step":
        return Invocation(
            (x, values),
            {"where": draw(st.sampled_from(("pre", "post", "mid")))},
        )
    if builder == "stairs":
        increments = np.abs(_draw_values(draw, n + 1)) + 0.25
        edges = np.cumsum(increments)
        return Invocation(
            (values, edges),
            {"where": draw(st.sampled_from(("pre", "post", "mid")))},
        )
    if builder == "stem":
        base = values - np.abs(_draw_values(draw, n))
        return Invocation((x, values), {"base": base, "marker": draw(st.booleans())})
    if builder == "segments":
        return Invocation((x, values, x + spacing * 0.5, values + 1.0), {})
    if builder == "triangle_mesh":
        return Invocation(
            (x, values, x + 0.5, values + 0.25, x + 0.25, values + 1.0),
            {},
        )
    if builder in {"bar", "column"}:
        categories = np.asarray([f"category-{index}" for index in range(n)], dtype=object)
        return Invocation(
            (categories, values),
            {"orientation": draw(st.sampled_from(("vertical", "horizontal")))},
        )
    if builder == "heatmap":
        rows = draw(st.integers(min_value=1, max_value=5))
        cols = draw(st.integers(min_value=1, max_value=5))
        z = _draw_values(draw, rows * cols).reshape(rows, cols)
        return Invocation((z,), {})
    raise AssertionError(f"missing valid strategy for {builder}")


@st.composite
def _invalid_invocation(draw: st.DrawFn, builder: str) -> InvalidInvocation:
    """Generate a documented invalid class for one public builder."""
    n = draw(st.integers(min_value=2, max_value=10))
    x = np.arange(n, dtype=np.float64)
    y = _draw_values(draw, n)
    short = y[:-1]

    cases: dict[str, InvalidInvocation] = {
        "line": InvalidInvocation((x, short), {}, "cardinality", "equal length"),
        "area": InvalidInvocation((x, y), {"base": short}, "cardinality", "base must have"),
        "scatter": InvalidInvocation(
            (x, y), {"color": short}, "channel-cardinality", "color array must be 1-D length"
        ),
        "histogram": InvalidInvocation((y,), {"bins": 0}, "domain", "bins must be positive"),
        "hist": InvalidInvocation((y,), {"bins": 0}, "domain", "bins must be positive"),
        "error_band": InvalidInvocation((x, y, short), {}, "cardinality", "upper must have length"),
        "errorbar": InvalidInvocation((x, y), {"yerr": -1.0}, "domain", "non-negative"),
        "box": InvalidInvocation((y,), {"orientation": "diagonal"}, "enum", "orientation"),
        "violin": InvalidInvocation((y,), {"bins": 3}, "domain", "between 4 and 1024"),
        "ecdf": InvalidInvocation((y,), {"bins": 0}, "domain", "positive integer"),
        "hexbin": InvalidInvocation((x, y), {"gridsize": 0}, "domain", "gridsize"),
        "contour": InvalidInvocation((y,), {}, "shape", "2-D matrix"),
        "step": InvalidInvocation((x, y), {"where": "sideways"}, "enum", "where"),
        "stairs": InvalidInvocation((y, x), {}, "cardinality", "edges must have length"),
        "stem": InvalidInvocation((x, y), {"base": short}, "cardinality", "base must have"),
        "segments": InvalidInvocation(
            (x, y, x, short), {}, "cardinality", "coordinate columns must have equal length"
        ),
        "triangle_mesh": InvalidInvocation(
            (x, y, x, y, x, short), {}, "cardinality", "coordinate columns must have equal length"
        ),
        "bar": InvalidInvocation((x, y), {"mode": "overlap"}, "enum", "mode"),
        "column": InvalidInvocation((x, y), {"orientation": "diagonal"}, "enum", "orientation"),
        "heatmap": InvalidInvocation((y,), {}, "shape", "must be 2-D or RGB"),
    }
    return cases[builder]


VALID_STRATEGIES = {builder: _valid_invocation(builder) for builder in PUBLIC_BUILDERS}
INVALID_STRATEGIES = {builder: _invalid_invocation(builder) for builder in PUBLIC_BUILDERS}


def check_payload(fig: Figure) -> None:
    """P2-P7 on a successfully built figure."""
    spec, blob = fig.build_payload()
    spec2, blob2 = fig.build_payload()
    assert blob == blob2, "P7: blob must be deterministic"
    assert json.dumps(spec) == json.dumps(spec2), "P7: spec must be deterministic"
    json.dumps(spec)  # P2

    cols = spec["columns"]
    for c in cols:
        assert 0 <= c["byte_offset"] <= len(blob), "P3"
        itemsize = {"u8": 1, "u32": 4, "f64": 8}.get(c.get("dtype"), 4)
        assert c["byte_offset"] + itemsize * c["len"] <= len(blob), "P3"

    def col_ref(ref):
        assert isinstance(ref, int) and 0 <= ref < len(cols), "P3"
        c = cols[ref]
        return np.frombuffer(blob, np.float32, count=c["len"], offset=c["byte_offset"])

    for tr in spec["traces"]:
        assert tr["tier"] in ("direct", "decimated", "density"), "P6"
        for key in ("x", "y"):
            if isinstance(tr.get(key), int):
                geom = col_ref(tr[key])
                assert np.isfinite(geom).all(), f"P4: non-finite in {key} buffer"
        for key in ("open", "high", "low", "close", "base"):
            if isinstance(tr.get(key), int):
                assert np.isfinite(col_ref(tr[key])).all(), f"P4: {key}"

    for ax in ("x_axis", "y_axis"):
        lo, hi = spec[ax]["range"]
        assert math.isfinite(lo) and math.isfinite(hi) and lo < hi, "P5"


def build_or_reject(builder, *args, **kwargs):
    """P1: builders either build or raise the documented error classes."""
    fig = Figure()
    try:
        getattr(fig, builder)(*args, **kwargs)
    except ACCEPTABLE:
        return None
    try:
        check_payload(fig)
    except ACCEPTABLE:
        return None  # e.g. nothing finite to autorange — documented rejection
    return fig


@pytest.mark.parametrize("builder", PUBLIC_BUILDERS)
@VALID_COMMON
@given(data=st.data())
def test_every_public_builder_has_a_valid_strategy(builder, data):
    """Every cataloged builder must succeed for data valid by construction."""
    invocation = data.draw(VALID_STRATEGIES[builder], label=builder)
    fig = Figure()
    result = getattr(fig, builder)(*invocation.args, **invocation.kwargs)
    assert result is fig
    assert fig.traces, f"{builder} accepted valid data without producing a trace"
    check_payload(fig)


def test_violin_documented_four_bin_minimum_is_valid():
    fig = Figure().violin([1.0, 2.0, 3.0], bins=4)

    assert len(fig.traces) == 1
    assert len(fig.traces[0].x0) == 4
    check_payload(fig)


@pytest.mark.parametrize("builder", PUBLIC_BUILDERS)
@INVALID_COMMON
@given(data=st.data())
def test_every_public_builder_has_a_classified_invalid_strategy(builder, data):
    """Invalid strategies reject predictably and never leave partial state."""
    invocation = data.draw(INVALID_STRATEGIES[builder], label=builder)
    assert invocation.category in {"cardinality", "channel-cardinality", "domain", "enum", "shape"}
    fig = Figure()
    with pytest.raises(ValueError, match=invocation.match):
        getattr(fig, builder)(*invocation.args, **invocation.kwargs)
    assert fig.traces == []
    assert fig.store.columns == []
    assert fig.store._by_key == {}
    assert fig._axis_categories == {}


class SyntheticLateFailure(RuntimeError):
    """Injected after a trace was inserted, at the latest shared mutation point."""


class _AppendThenFail(list):
    def append(self, item: Any) -> None:
        super().append(item)
        raise SyntheticLateFailure("synthetic failure after trace append")


def _freeze(value: Any) -> Any:
    """Bitwise, identity-aware snapshot used only for rollback comparison."""
    if value is None or isinstance(value, (str, bytes, bool, int)):
        return value
    if isinstance(value, float):
        return ("float64", struct.pack("=d", value))
    if isinstance(value, np.ndarray):
        return (
            "ndarray",
            id(value),
            value.dtype.str,
            value.shape,
            value.strides,
            value.flags.writeable,
            value.tobytes(order="A"),
        )
    if isinstance(value, np.generic):
        return ("numpy-scalar", value.dtype.str, value.tobytes())
    if isinstance(value, weakref.finalize):
        return ("finalize", id(value), value.alive)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        field_names = {field.name for field in dataclasses.fields(value)}
        declared = tuple(
            (field.name, _freeze(getattr(value, field.name))) for field in dataclasses.fields(value)
        )
        # cached_property values and amortized column buffers live outside
        # dataclass fields; include them explicitly so this is a cache snapshot.
        extras = tuple(
            (key, _freeze(item)) for key, item in vars(value).items() if key not in field_names
        )
        return (type(value).__qualname__, id(value), declared, extras)
    if isinstance(value, dict):
        return (
            "dict",
            tuple((_freeze(key), _freeze(item)) for key, item in value.items()),
        )
    if isinstance(value, (list, tuple)):
        return (type(value).__qualname__, tuple(_freeze(item) for item in value))
    return (type(value).__qualname__, id(value), repr(value))


@dataclass(frozen=True)
class _FigureState:
    traces: Any
    columns: Any
    dedup_keys: Any
    axes: Any
    categories: Any
    annotations: Any
    interaction: Any
    caches: Any
    pyramids: Any
    drill: Any


def _snapshot_figure(fig: Figure) -> _FigureState:
    columns = tuple(fig.store.columns)
    return _FigureState(
        traces=_freeze(tuple(fig.traces)),
        columns=_freeze(columns),
        dedup_keys=tuple(fig.store._by_key.items()),
        axes=_freeze((fig.axis_options, fig._active_axis_ids)),
        categories=_freeze(fig._axis_categories),
        annotations=_freeze(fig.annotations),
        interaction=_freeze(fig.interaction),
        caches=_freeze(
            tuple(
                (
                    column._zone,
                    getattr(column, "_grow", None),
                    column.ingest_copies,
                )
                for column in columns
            )
        ),
        pyramids=tuple(
            (
                trace._pyr_handle,
                _freeze(trace._pyr_finalizer),
            )
            for trace in fig.traces
        ),
        drill=_freeze(
            tuple((trace.shipped_sel, trace.drill_mode, trace.drill_seq) for trace in fig.traces)
        ),
    )


def _seed_figure(monkeypatch: pytest.MonkeyPatch) -> tuple[Figure, Any]:
    """Create nonempty state across every rollback surface in TST-NI-006."""
    fig = Figure(title="seeded transaction")
    seed_x = np.asarray([0.0, 1.0, 2.0, 3.0])
    seed_y = np.asarray([0.0, 1.0, 4.0, 9.0])
    fig.scatter(seed_x, seed_y, name="seed-density", density=True)
    seed_trace = fig.traces[0]
    fig.bar(np.asarray(["seed-a", "seed-b"], dtype=object), np.asarray([2.0, 3.0]))
    fig.set_axis("x2", label="seed secondary", domain=(-5.0, 5.0), side="top")
    fig.text(1.0, 4.0, "seed annotation", style={"font_weight": 600})
    fig.interaction = {"mode": "select", "selection": "seeded"}

    # Exercise materialized zone-map cached_properties, not only raw columns.
    for column in fig.store.columns:
        zone = column.zone
        _ = (
            zone.min,
            zone.max,
            zone.positive_min,
            zone.positive_max,
            zone.count,
            zone.null_count,
        )

    # Build a real, tiny native pyramid. This proves the handle and finalizer
    # survive rollback exactly without allocating the production 2048² cache.
    monkeypatch.setattr(interaction, "PYRAMID_MIN_POINTS", 1)
    monkeypatch.setattr(interaction, "PYRAMID_BASE_DIM", 8)
    assert interaction._ensure_pyramid(seed_trace)
    seed_trace.shipped_sel = np.asarray([3, 1], dtype=np.uint32)
    seed_trace.drill_mode = True
    seed_trace.drill_seq = 17
    fig.traces = _AppendThenFail(fig.traces)
    return fig, seed_trace


ROLLBACK_INVOCATIONS = {
    "line": Invocation(([2.0, 0.0, 1.0], [2.0, 0.0, 1.0]), {}),
    "area": Invocation(([2.0, 0.0, 1.0], [3.0, 1.0, 2.0]), {"base": [1.0, 0.0, 0.5]}),
    "scatter": Invocation(([0.0, 1.0, 2.0], [2.0, 1.0, 3.0]), {"color": [0.1, 0.2, 0.3]}),
    "histogram": Invocation(([0.0, 1.0, 2.0, 3.0],), {"bins": 3}),
    "hist": Invocation(([0.0, 1.0, 2.0, 3.0],), {"bins": 3}),
    "error_band": Invocation(([0.0, 1.0, 2.0], [0.0, 0.5, 1.0], [1.0, 1.5, 2.0]), {}),
    "errorbar": Invocation(([0.0, 1.0], [2.0, 3.0]), {"xerr": 0.1, "yerr": 0.2}),
    "box": Invocation(([1.0, 2.0, 3.0, 4.0],), {"show_outliers": False}),
    "violin": Invocation(([1.0, 2.0, 3.0, 4.0],), {"bins": 8}),
    "ecdf": Invocation(([3.0, 1.0, 2.0, 2.0],), {}),
    "hexbin": Invocation(
        ([0.0, 0.5, 1.0], [0.0, 1.0, 0.5]),
        {"gridsize": 4, "range": ((-0.5, 1.5), (-0.5, 1.5))},
    ),
    "contour": Invocation((np.asarray([[0.0, 1.0], [2.0, 3.0]]),), {"levels": [1.5]}),
    "step": Invocation(([0.0, 1.0, 2.0], [2.0, 1.0, 3.0]), {"where": "mid"}),
    "stairs": Invocation(([2.0, 1.0, 3.0], [0.0, 1.0, 2.0, 3.0]), {}),
    "stem": Invocation(([0.0, 1.0], [2.0, 3.0]), {"base": [0.5, 1.0]}),
    "segments": Invocation(([0.0, 1.0], [2.0, 3.0], [1.0, 2.0], [3.0, 4.0]), {}),
    "triangle_mesh": Invocation(([0.0], [0.0], [1.0], [0.0], [0.5], [1.0]), {}),
    "bar": Invocation((np.asarray(["new-a", "new-b"]), [1.0, 2.0]), {}),
    "column": Invocation((np.asarray(["new-a", "new-b"]), [1.0, 2.0]), {}),
    "heatmap": Invocation((np.asarray([[0.0, 1.0], [2.0, 3.0]]),), {}),
}


@pytest.mark.parametrize("builder", PUBLIC_BUILDERS)
def test_every_public_builder_rolls_back_an_injected_late_failure(builder, monkeypatch):
    """P8: failed builders are exact transactions over an already-live chart."""
    fig, pyramid_trace = _seed_figure(monkeypatch)
    before = _snapshot_figure(fig)
    invocation = ROLLBACK_INVOCATIONS[builder]
    try:
        with pytest.raises(SyntheticLateFailure, match="after trace append"):
            getattr(fig, builder)(*invocation.args, **invocation.kwargs)
        assert _snapshot_figure(fig) == before
    finally:
        interaction._free_pyramid(pyramid_trace)


# -- per-builder properties ---------------------------------------------------


@COMMON
@given(x=hostile_array(), y=hostile_array())
def test_line_hostile(x, y):
    fig = build_or_reject("line", x, y)
    if fig is None:
        return
    # P5 for lines: finite data lies inside the padded autorange
    spec, _ = fig.build_payload()
    fx = x[np.isfinite(x)]
    if len(fx):
        lo, hi = spec["x_axis"]["range"]
        assert lo <= fx.min() and fx.max() <= hi


@COMMON
@given(
    x=hostile_array(),
    y=hostile_array(),
    color=st.one_of(st.none(), hostile_array()),
    size=st.one_of(st.just(4.0), hostile_array()),
)
def test_scatter_hostile(x, y, color, size):
    build_or_reject("scatter", x, y, color=color, size=size)


@COMMON
@given(x=hostile_array(), y=hostile_array(), base=st.one_of(finite_floats, hostile_array()))
def test_area_hostile(x, y, base):
    build_or_reject("area", x, y, base=base)


@COMMON
@given(
    values=hostile_array(),
    bins=st.one_of(st.just("auto"), st.integers(min_value=-3, max_value=512)),
    density=st.booleans(),
)
def test_histogram_hostile(values, bins, density):
    fig = build_or_reject("histogram", values, bins=bins, density=density)
    if fig is None:
        return
    # histogram truthfulness: total count equals finite in-range rows
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    if not density and isinstance(tr.get("bar"), dict) and isinstance(tr["bar"].get("value1"), int):
        c = spec["columns"][tr["bar"]["value1"]]
        heights = np.frombuffer(blob, np.float32, count=c["len"], offset=c["byte_offset"])
        assert heights.sum() <= np.isfinite(values).sum() + 1e-3


@COMMON
@given(
    y=hostile_array(min_size=0, max_size=64),
    labels=st.booleans(),
)
def test_bar_hostile(y, labels):
    x = (
        np.array([f"c{i}" for i in range(len(y))], dtype=object)
        if labels
        else np.arange(len(y), dtype=np.float64)
    )
    build_or_reject("bar", x, y)


@COMMON
@given(
    z=st.lists(
        st.lists(hostile_floats, min_size=1, max_size=12),
        min_size=1,
        max_size=12,
    ).filter(lambda rows: len({len(r) for r in rows}) == 1),
)
def test_heatmap_hostile(z):
    build_or_reject("heatmap", np.asarray(z, dtype=np.float64))


@COMMON
@given(x=hostile_array(min_size=1), extra=st.integers(min_value=1, max_value=7))
def test_length_mismatch_always_valueerror(x, extra):
    y = np.zeros(len(x) + extra)
    for builder in ("line", "scatter", "area"):
        with pytest.raises(ACCEPTABLE):
            getattr(Figure(), builder)(x, y)


@COMMON
@given(x=hostile_array(min_size=2, max_size=200))
def test_line_sorts_unsorted_x(x):
    y = np.zeros(len(x))
    fig = build_or_reject("line", x, y)
    if fig is None:
        return
    xs = fig.traces[0].x.values
    finite = xs[np.isfinite(xs)]
    assert np.all(np.diff(finite) >= 0), "line x must be non-decreasing after ingest"


@COMMON
@given(
    x=hostile_array(max_size=100),
    y=hostile_array(max_size=100),
    w=st.integers(min_value=100, max_value=2000),
)
def test_spec_size_screen_bounded(x, y, w):
    """P6: spec JSON stays small regardless of N — data rides the blob."""
    fig = build_or_reject("scatter", x, y)
    if fig is None:
        return
    spec, _ = fig.build_payload(px_width=w)
    assert len(json.dumps(spec)) < 20_000
