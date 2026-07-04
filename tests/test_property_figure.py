"""Property-based tests for the figure builders (hostile-input surface).

Hypothesis drives every public builder with adversarial arrays — NaN, ±inf,
huge/tiny magnitudes, empty, constant, unsorted, mismatched lengths — and
checks the invariants the wire contract promises rather than specific values:

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

Requires the `hypothesis` dev extra; skipped cleanly where it is absent
(e.g. the no-PyPI sandbox) — CI installs `.[dev]` and runs the full suite.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

hyp = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from fastcharts import Figure  # noqa: E402

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
        assert c["byte_offset"] + 4 * c["len"] <= len(blob), "P3"

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
