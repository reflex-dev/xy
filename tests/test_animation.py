"""Declarative animation and binary keyed-transition contracts."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

import numpy as np
import pytest

import xy
import xy.components as component_api
from xy import kernels as k


def _column(blob: bytes, spec: dict, index: int) -> np.ndarray:
    meta = spec["columns"][index]
    dtype = np.uint32 if meta.get("dtype") == "u32" else np.float32
    return np.frombuffer(blob, dtype=dtype, count=meta["len"], offset=meta["byte_offset"])


def _python_transition_key_reference(values) -> np.ndarray:
    """The scalar encoder retained as the policy/fallback oracle."""
    arr = np.asarray(values, dtype=object)
    result = np.empty((len(arr), 2), dtype=np.uint32, order="F")
    seen: dict[bytes, int] = {}
    digests: dict[bytes, bytes] = {}
    for index, raw in enumerate(arr):
        token = component_api._transition_key_token(raw, index)
        previous = seen.get(token)
        if previous is not None:
            raise ValueError(
                f"reference key contains duplicate value at rows {previous} and {index}"
            )
        seen[token] = index
        digest = hashlib.blake2s(token, digest_size=8, person=b"xykeyv1").digest()
        collision = digests.get(digest)
        if collision is not None and collision != token:
            raise ValueError("reference key produced an identity digest collision")
        digests[digest] = token
        result[index, 0] = int.from_bytes(digest[:4], "little")
        result[index, 1] = int.from_bytes(digest[4:], "little")
    return result


def _swapped(values: np.ndarray) -> np.ndarray:
    return values.astype(values.dtype.newbyteorder("S"))


def test_animation_component_serializes_without_callbacks() -> None:
    started = lambda event: event  # noqa: E731
    ended = lambda event: event  # noqa: E731
    chart = xy.scatter_chart(
        xy.scatter(x=[1.0], y=[2.0]),
        xy.animation(
            enabled=True,
            delay=20,
            duration=250,
            easing=(0.2, 0.8, 0.3, 1.0),
            match="append",
            enter="scale",
            on_start=started,
            on_end=ended,
        ),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["animation"] == {
        "enabled": True,
        "delay": 20.0,
        "duration": 250.0,
        "easing": [0.2, 0.8, 0.3, 1.0],
        "match": "append",
        "enter": "scale",
        "update": "interpolate",
        "interpolate": ["position", "size", "color", "domain"],
    }
    encoded = json.dumps(spec)
    assert "lambda" not in encoded
    assert "on_start" not in encoded
    assert "on_end" not in encoded


def test_spring_policy_is_bounded_and_serializable() -> None:
    spring = xy.spring(stiffness=210, damping=28, mass=0.8)
    spec = xy.animation(easing=spring).to_spec()
    assert spec["easing"] == {
        "type": "spring",
        "stiffness": 210.0,
        "damping": 28.0,
        "mass": 0.8,
    }
    with pytest.raises(ValueError, match="spring damping must be positive"):
        xy.spring(damping=0)


@pytest.mark.parametrize(
    ("kind", "mark"),
    [
        ("line", lambda: xy.line([0, 1], [2, 3], key=["a", "b"])),
        ("area", lambda: xy.area([0, 1], [2, 3], key=["a", "b"])),
        ("bar", lambda: xy.bar([0, 1], [2, 3], key=["a", "b"])),
        ("column", lambda: xy.column([0, 1], [2, 3], key=["a", "b"])),
        ("scatter", lambda: xy.scatter([0, 1], [2, 3], key=["a", "b"])),
        (
            "error_band",
            lambda: xy.error_band(
                [0, 1],
                [1, 2],
                [3, 4],
                key=["a", "b"],
            ),
        ),
        (
            "errorbar",
            lambda: xy.errorbar(
                [0, 1],
                [2, 3],
                yerr=[0.2, 0.3],
                key=["a", "b"],
            ),
        ),
    ],
)
def test_common_keyed_animation_contract_across_mark_kinds(
    kind: str,
    mark,
) -> None:
    chart = xy.chart(
        mark(),
        xy.animation(
            enabled="auto",
            delay=15,
            duration=450,
            easing="spring",
            match="key",
            enter="auto",
            update="interpolate",
        ),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["animation"] == {
        "enabled": "auto",
        "delay": 15.0,
        "duration": 450.0,
        "easing": {
            "type": "spring",
            "stiffness": 170.0,
            "damping": 26.0,
            "mass": 1.0,
        },
        "match": "key",
        "enter": "auto",
        "update": "interpolate",
        "interpolate": ["position", "size", "color", "domain"],
    }
    assert {trace["kind"] for trace in spec["traces"]} == {kind}
    assert all(set(trace["keys"]) == {"lo", "hi"} for trace in spec["traces"])


def test_keyed_scatter_ships_identity_as_binary_u32_words() -> None:
    chart = xy.scatter_chart(
        xy.scatter(
            x="x",
            y="y",
            key="country",
            data={"x": [1.0, 2.0], "y": [3.0, 4.0], "country": ["ES", "FR"]},
        ),
        xy.animation(match="key"),
    )

    spec, blob = chart.figure().build_payload()
    trace = spec["traces"][0]

    assert set(trace["keys"]) == {"lo", "hi"}
    lo = _column(blob, spec, trace["keys"]["lo"])
    hi = _column(blob, spec, trace["keys"]["hi"])
    assert lo.dtype == np.uint32
    assert hi.dtype == np.uint32
    assert len(lo) == len(hi) == 2
    assert len({(int(a), int(b)) for a, b in zip(lo, hi, strict=True)}) == 2
    assert [column.get("dtype") for column in spec["columns"]].count("u32") == 2


def test_stable_keys_are_type_sensitive_and_deterministic() -> None:
    chart = xy.scatter_chart(
        xy.scatter(x=[1.0, 2.0, 3.0], y=[3.0, 4.0, 5.0], key=[1, 1.0, True]),
        xy.animation(match="key"),
    )

    first_spec, first_blob = chart.figure().build_payload()
    second_spec, second_blob = chart.figure().build_payload()
    trace = first_spec["traces"][0]
    pairs = list(
        zip(
            _column(first_blob, first_spec, trace["keys"]["lo"]),
            _column(first_blob, first_spec, trace["keys"]["hi"]),
            strict=True,
        )
    )

    assert len({(int(lo), int(hi)) for lo, hi in pairs}) == 3
    assert first_spec == second_spec
    assert first_blob == second_blob


@pytest.mark.parametrize(
    "keys",
    [
        pytest.param(["", "café", "猫"], id="list-unicode"),
        pytest.param([b"", b"ascii", b"\xff"], id="list-bytes"),
        # The two-byte ``s:``/``y:`` prefix makes these token lengths
        # 62, 63, 64, 65, and 129, spanning BLAKE2s full/final blocks.
        pytest.param(
            ["a" * size for size in (60, 61, 62, 63, 127)],
            id="list-unicode-blake2-block-boundaries",
        ),
        pytest.param(
            [b"a" * size for size in (60, 61, 62, 63, 127)],
            id="list-bytes-blake2-block-boundaries",
        ),
        pytest.param([False, True], id="list-bool"),
        pytest.param([-7, 0, 2**40], id="list-int"),
        pytest.param([0.0, -0.0, np.nextafter(0.0, 1.0), 1.5], id="list-float"),
        pytest.param(np.array(["", "café", "猫"], dtype="U4"), id="numpy-unicode"),
        pytest.param(
            np.array(["a\x00b", "plain"], dtype="U5"),
            id="numpy-unicode-embedded-nul",
        ),
        pytest.param(
            _swapped(np.array(["", "β", "猫"], dtype="U2")),
            id="numpy-unicode-swapped",
        ),
        pytest.param(np.array([b"", b"abc", b"\xff"], dtype="S3"), id="numpy-bytes"),
        pytest.param(
            np.array([b"a\x00b", b"plain"], dtype="S5"),
            id="numpy-bytes-embedded-nul",
        ),
        pytest.param(np.array([False, True], dtype=np.bool_), id="numpy-bool"),
        pytest.param(np.array([-128, 0, 127], dtype=np.int8), id="numpy-int8"),
        pytest.param(np.array([-32768, 0, 32767], dtype=np.int16), id="numpy-int16"),
        pytest.param(
            _swapped(np.array([-(2**31), 0, 2**31 - 1], dtype=np.int32)),
            id="numpy-int32-swapped",
        ),
        pytest.param(
            np.array([-(2**63), 0, 2**63 - 1], dtype=np.int64),
            id="numpy-int64",
        ),
        pytest.param(np.array([0, 1, 255], dtype=np.uint8), id="numpy-uint8"),
        pytest.param(np.array([0, 1, 65535], dtype=np.uint16), id="numpy-uint16"),
        pytest.param(
            _swapped(np.array([0, 1, 2**32 - 1], dtype=np.uint32)),
            id="numpy-uint32-swapped",
        ),
        pytest.param(
            np.array([0, 1, 2**64 - 1], dtype=np.uint64),
            id="numpy-uint64",
        ),
        pytest.param(
            np.array([0.0, -0.0, 0.5], dtype=np.float16),
            id="numpy-float16",
        ),
        pytest.param(
            np.array([0.0, -0.0, 1.25], dtype=np.float32),
            id="numpy-float32",
        ),
        pytest.param(
            _swapped(
                np.array(
                    [0.0, -0.0, np.nextafter(0.0, 1.0), -2.25],
                    dtype=np.float64,
                )
            ),
            id="numpy-float64-swapped-subnormal",
        ),
        # Object storage still routes when every row is one builtin type —
        # this is the shape a pandas string column arrives in.
        pytest.param(np.array(["a", "b"], dtype=object), id="object-array"),
        pytest.param(np.array([1.25, 2.5], dtype=object), id="object-floats"),
        pytest.param(np.array([3, -4], dtype=object), id="object-ints"),
        # An interior NUL survives fixed-width storage intact; only a
        # *trailing* one is ambiguous against padding.
        pytest.param(["a\x00b", "plain"], id="list-unicode-interior-nul"),
        pytest.param([b"a\x00b", b"plain"], id="list-bytes-interior-nul"),
    ],
)
def test_native_transition_key_fast_paths_match_python_reference(keys, monkeypatch) -> None:
    calls: list[np.ndarray] = []
    native = k.transition_keys_fixed

    def tracked(values: np.ndarray, label: str):
        calls.append(values)
        return native(values, label)

    monkeypatch.setattr(k, "transition_keys_fixed", tracked)
    actual = component_api._encode_transition_keys(keys, len(keys), "parity key")
    expected = _python_transition_key_reference(keys)

    assert len(calls) == 1
    np.testing.assert_array_equal(actual, expected)
    assert actual.dtype == np.uint32
    assert actual.shape == (len(keys), 2)
    assert actual[:, 0].flags.c_contiguous
    assert actual[:, 1].flags.c_contiguous


@pytest.mark.parametrize(
    "keys",
    [
        pytest.param([1, "1", True, b"1"], id="mixed-builtins"),
        pytest.param(np.array([1, "1"], dtype=object), id="object-array-mixed"),
        # A trailing NUL is indistinguishable from fixed-width padding, so
        # these must keep their exact Python tokens.
        pytest.param(["a\x00", "plain"], id="list-unicode-trailing-nul"),
        pytest.param([b"a\x00", b"plain"], id="list-bytes-trailing-nul"),
        pytest.param(
            [dt.date(2024, 1, 1), dt.date(2024, 1, 2)],
            id="dates",
        ),
        pytest.param(
            [
                dt.datetime(2024, 1, 1, 12, 30),
                dt.datetime(2024, 1, 1, 12, 31),
            ],
            id="datetimes",
        ),
        pytest.param([2**100, 2**100 + 1], id="wide-python-ints"),
    ],
)
def test_transition_key_object_policy_uses_python_reference(keys, monkeypatch) -> None:
    def unexpected_native(_values: np.ndarray, _label: str):
        raise AssertionError("object-policy key values must retain the Python oracle")

    monkeypatch.setattr(k, "transition_keys_fixed", unexpected_native)
    actual = component_api._encode_transition_keys(keys, len(keys), "fallback key")
    np.testing.assert_array_equal(actual, _python_transition_key_reference(keys))


@pytest.mark.parametrize(
    "keys",
    [
        [f"k{index}" for index in range(16)] + ["z" * 256],
        [f"k{index}".encode() for index in range(16)] + [b"z" * 256],
    ],
)
def test_skewed_sequence_keys_avoid_fixed_width_memory_amplification(keys, monkeypatch) -> None:
    def unexpected_native(_values: np.ndarray, _label: str):
        raise AssertionError("skewed sequence keys must retain the Python oracle")

    monkeypatch.setattr(k, "transition_keys_fixed", unexpected_native)
    actual = component_api._encode_transition_keys(keys, len(keys), "skewed key")
    np.testing.assert_array_equal(actual, _python_transition_key_reference(keys))


@pytest.mark.parametrize(
    ("keys", "row"),
    [
        (np.array([1.0, np.nan], dtype=np.float64), 1),
        (np.array([np.inf, 1.0], dtype=np.float32), 0),
        ([-np.inf, 1.0], 0),
    ],
)
def test_nonfinite_native_float_keys_retain_exact_python_row_error(keys, row) -> None:
    with pytest.raises(ValueError, match=rf"animation key must be finite at row {row}"):
        component_api._encode_transition_keys(keys, len(keys), "finite key")


@pytest.mark.parametrize(
    "keys",
    [
        ["a", "b", "a", "b"],
        np.array([b"a", b"b", b"a", b"b"], dtype="S1"),
        np.array([7, 9, 7, 9], dtype=">i4"),
        np.array([1.5, 2.5, 1.5, 2.5], dtype=np.float64),
    ],
)
def test_native_transition_key_duplicates_report_first_rows(keys) -> None:
    with pytest.raises(
        ValueError,
        match=r"duplicate key contains duplicate value at rows 0 and 2",
    ):
        component_api._encode_transition_keys(keys, len(keys), "duplicate key")


def test_transition_key_empty_shape_and_length_semantics() -> None:
    for keys in ([], np.array([], dtype="U1")):
        encoded = component_api._encode_transition_keys(keys, 0, "empty key")
        assert encoded.shape == (0, 2)
        assert encoded.dtype == np.uint32

    with pytest.raises(ValueError, match="shape key must be one-dimensional"):
        component_api._encode_transition_keys([["a"], ["b"]], 2, "shape key")
    with pytest.raises(ValueError, match="length key must have length 3, got 2"):
        component_api._encode_transition_keys(["a", "b"], 3, "length key")


@pytest.mark.parametrize(
    "column",
    [
        pytest.param(["alpha", "beta", "gamma"], id="string-column"),
        pytest.param([3, -4, 5], id="integer-column"),
        pytest.param([1.5, -0.0, 2.25], id="float-column"),
        pytest.param([True, False], id="bool-column"),
    ],
)
def test_dataframe_key_columns_reach_the_native_encoder(column, monkeypatch) -> None:
    """`data=df, key="id"` resolves to a Series, not an ndarray (§ routing)."""
    pd = pytest.importorskip("pandas")
    series = pd.Series(column)
    calls: list[np.ndarray] = []
    native = k.transition_keys_fixed

    def tracked(values: np.ndarray, label: str):
        calls.append(values)
        return native(values, label)

    monkeypatch.setattr(k, "transition_keys_fixed", tracked)
    actual = component_api._encode_transition_keys(series, len(series), "frame key")

    assert len(calls) == 1
    np.testing.assert_array_equal(actual, _python_transition_key_reference(column))


def test_dataframe_key_column_with_missing_values_keeps_its_python_error() -> None:
    pd = pytest.importorskip("pandas")
    series = pd.Series([1.0, None, 3.0], dtype="Float64")
    with pytest.raises(ValueError, match="animation key is missing at row 1"):
        component_api._encode_transition_keys(series, 3, "frame key")


def test_native_transition_key_argument_errors_are_loud() -> None:
    """A layout the kernel refuses is a bug, not a reason to degrade silently.

    Status 1 means "declined this data, use the oracle"; status 4 means the
    caller sent a layout the ABI does not define. Collapsing the two would let
    a `_native.py`/`valid_layout` drift turn into a silent ~7x regression that
    every existing assertion still passes.
    """
    with pytest.raises(ValueError, match="must be a non-object 1-D array"):
        k.transition_keys_fixed(np.array(["a", "b"], dtype=object), "bad key")
    with pytest.raises(ValueError, match="must use Unicode, bytes, bool, integer, or float"):
        k.transition_keys_fixed(np.array(["2024-01-01"], dtype="datetime64[D]"), "bad key")

    # The wrapper's own dtype gate and Rust's `valid_layout` agree today, so
    # reaching status 4 needs the seam forced open. What matters is that it
    # raises rather than returning the None that means "use the oracle".
    from xy import _native

    original = _native._lib.xy_transition_keys_fixed
    try:
        _native._lib.xy_transition_keys_fixed = lambda *_args: 4
        with pytest.raises(RuntimeError, match=r"rejected the .* layout it was handed"):
            _native.transition_keys_fixed(np.array([b"ab"], dtype="S2"), "bad key")
    finally:
        _native._lib.xy_transition_keys_fixed = original


def _keyed_scatter(animation, n: int = 8):
    x = [float(i) for i in range(n)]
    marks = [xy.scatter(x=x, y=x, key=[f"k{i}" for i in range(n)])]
    return xy.scatter_chart(*marks, *([animation] if animation is not None else [])).figure()


@pytest.mark.parametrize(
    ("animation", "ships"),
    [
        pytest.param(xy.animation(match="key"), True, id="match-key"),
        pytest.param(xy.animation(match="index"), False, id="match-index"),
        # `match` defaults to "index", so a bare animation() never key-matches.
        pytest.param(xy.animation(duration=250), False, id="match-defaulted"),
        pytest.param(xy.animation(match="key", enabled=False), False, id="disabled"),
        pytest.param(None, False, id="no-animation-spec"),
    ],
)
def test_identity_planes_ship_only_when_the_client_can_key_match(animation, ships) -> None:
    """`key=` alone must not put two dead u32 columns on the wire."""
    figure = _keyed_scatter(animation)
    spec, _buffers = figure.build_payload_split()
    trace = spec["traces"][0]

    assert ("keys" in trace) is ships
    assert (figure.traces[0].transition_keys is not None) is ships


@pytest.mark.parametrize(
    "animation",
    [
        pytest.param(xy.animation(match="index"), id="match-index"),
        pytest.param(xy.animation(enabled=False), id="disabled"),
        pytest.param(None, id="no-animation-spec"),
    ],
)
def test_key_validation_still_runs_when_planes_are_skipped(animation) -> None:
    """Uniqueness and typing are construction contract, not animation policy."""
    marks = xy.scatter(x=[1.0, 2.0, 3.0], y=[1.0, 2.0, 3.0], key=["a", "b", "a"])
    with pytest.raises(ValueError, match="duplicate value at rows 0 and 2"):
        xy.scatter_chart(marks, *([animation] if animation is not None else [])).figure()

    bad = xy.scatter(x=[1.0, 2.0], y=[1.0, 2.0], key=[object(), object()])
    with pytest.raises(ValueError, match="animation key values must be"):
        xy.scatter_chart(bad, *([animation] if animation is not None else [])).figure()


def test_key_matching_payload_is_unchanged_by_the_skip() -> None:
    """The path that does key-match must be byte-identical to before."""
    spec, blob = _keyed_scatter(xy.animation(match="key"), n=32).build_payload()
    trace = spec["traces"][0]
    lo = _column(blob, spec, trace["keys"]["lo"])
    hi = _column(blob, spec, trace["keys"]["hi"])
    expected = _python_transition_key_reference([f"k{i}" for i in range(32)])
    np.testing.assert_array_equal(lo, expected[:, 0])
    np.testing.assert_array_equal(hi, expected[:, 1])


def test_mark_animation_spec_clobbers_chart_level_fields() -> None:
    """KNOWN BUG (reflex-dev/xy#329) — pinned so a fix is a deliberate change.

    `Animation.to_spec()` emits every field, and both the Python merge and the
    client's `{...spec.animation, ...trace.animation}` are plain dict spreads.
    So a mark-level `xy.animation(duration=90)` resets `match`, `easing`,
    `enter`, `update`, and `interpolate` to their defaults, silently turning
    off the chart-level `match="key"` the caller asked for.
    """
    figure = xy.scatter_chart(
        xy.scatter(
            x=[1.0, 2.0],
            y=[1.0, 2.0],
            key=["a", "b"],
            animation=xy.animation(duration=90),
        ),
        xy.animation(match="key", easing="linear"),
    ).figure()
    spec, _ = figure.build_payload_split()
    resolved = {**spec.get("animation", {}), **(spec["traces"][0].get("animation") or {})}

    assert resolved["match"] == "index"  # caller asked for "key"
    assert resolved["easing"] == "ease-out"  # caller asked for "linear"
    assert resolved["duration"] == 90.0  # the one field they meant to set

    # The same clobbering suppresses the match='key' requires key= guard.
    xy.scatter_chart(
        xy.scatter(x=[1.0, 2.0], y=[1.0, 2.0], animation=xy.animation(duration=90)),
        xy.animation(match="key"),
    ).figure()


def test_aggregate_tier_records_key_matching_fallback() -> None:
    chart = xy.scatter_chart(
        xy.scatter(
            x=[1.0, 2.0, 3.0],
            y=[3.0, 4.0, 5.0],
            key=["a", "b", "c"],
            density=True,
            # `match="key"` has to be restated here: a mark-level animation
            # spec is a full dict, so it resets every field the chart set.
            # See test_mark_animation_spec_clobbers_chart_level_fields.
            animation=xy.animation(duration=90, match="key"),
        ),
        xy.animation(match="key"),
    )

    spec, _ = chart.figure().build_payload()
    trace = spec["traces"][0]

    assert trace["tier"] == "density"
    assert trace["animation_fallback"] == "snap:aggregate"
    assert trace["animation"]["duration"] == 90.0
    assert "keys" not in trace


def test_mark_animation_overrides_chart_defaults() -> None:
    chart = xy.chart(
        xy.scatter(
            x=[1.0],
            y=[2.0],
            animation=xy.animation(enabled=True, duration=80, enter="scale"),
        ),
        xy.line(x=[1.0, 2.0], y=[2.0, 3.0], animation=False),
        xy.animation(enabled="auto", duration=500),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["animation"]["duration"] == 500.0
    assert spec["traces"][0]["animation"]["duration"] == 80.0
    assert spec["traces"][0]["animation"]["enter"] == "scale"
    assert spec["traces"][1]["animation"] == {"enabled": False}


def test_disabled_mark_does_not_require_chart_level_key_matching_identity() -> None:
    chart = xy.chart(
        xy.scatter(x=[1.0, 2.0], y=[3.0, 4.0], key=["a", "b"]),
        xy.line(x=[1.0, 2.0], y=[2.0, 3.0], animation=False),
        xy.animation(match="key"),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["traces"][1]["animation"] == {"enabled": False}
    assert "keys" not in spec["traces"][1]


def test_chart_and_mark_lifecycle_callbacks_reach_widget(monkeypatch) -> None:
    events: list[tuple[str, str]] = []
    chart = xy.scatter_chart(
        xy.scatter(
            x=[1.0],
            y=[2.0],
            animation=xy.animation(on_start=lambda event: events.append(("mark", event["phase"]))),
        ),
        xy.animation(on_start=lambda event: events.append(("chart", event["phase"]))),
    )

    class CapturingWidget:
        def __init__(self, figure, **kwargs):
            self.figure = figure
            self.kwargs = kwargs

    monkeypatch.setattr("xy.widget.FigureWidget", CapturingWidget)
    widget = chart.widget()
    widget.kwargs["on_animation_start"]({"phase": "enter"})

    assert events == [("chart", "enter"), ("mark", "enter")]


@pytest.mark.parametrize(
    ("keys", "match"),
    [
        (["ES", "ES"], "duplicate"),
        (["ES", None], "missing"),
        (["ES", float("nan")], "finite"),
        (["ES"], "length 2"),
    ],
)
def test_invalid_stable_keys_fail_clearly(keys: list[object], match: str) -> None:
    chart = xy.scatter_chart(
        xy.scatter(x=[1.0, 2.0], y=[3.0, 4.0], key=keys),
        xy.animation(match="key"),
    )
    with pytest.raises(ValueError, match=match):
        chart.figure()


def test_key_matching_requires_a_key_on_every_animated_mark() -> None:
    chart = xy.line_chart(
        xy.line(x=[1.0, 2.0], y=[3.0, 4.0]),
        xy.animation(match="key"),
    )
    with pytest.raises(ValueError, match="match='key' requires key"):
        chart.figure()


def test_line_keys_follow_the_geometry_sort_order() -> None:
    chart = xy.line_chart(
        xy.line(x=[3.0, 1.0, 2.0], y=[30.0, 10.0, 20.0], key=["c", "a", "b"]),
        xy.animation(match="key"),
    )
    figure = chart.figure()
    expected = xy.line_chart(
        xy.line(x=[1.0, 2.0, 3.0], y=[10.0, 20.0, 30.0], key=["a", "b", "c"]),
        xy.animation(match="key"),
    ).figure()

    np.testing.assert_array_equal(
        figure.traces[0].transition_keys, expected.traces[0].transition_keys
    )


def test_errorbar_expansion_has_unique_stable_segment_keys() -> None:
    chart = xy.errorbar_chart(
        xy.errorbar(
            x=[1.0, 2.0],
            y=[3.0, 4.0],
            yerr=[0.2, 0.3],
            cap_size=5,
            key=["a", "b"],
        ),
        xy.animation(match="key"),
    )

    spec, blob = chart.figure().build_payload()
    trace = spec["traces"][0]
    lo = _column(blob, spec, trace["keys"]["lo"])
    hi = _column(blob, spec, trace["keys"]["hi"])

    assert len(lo) == trace["n_marks"] == 6
    assert len({(int(a), int(b)) for a, b in zip(lo, hi, strict=True)}) == 6


def test_errorbar_role_qualification_rejects_binary_key_collisions() -> None:
    figure = xy.errorbar_chart(
        xy.errorbar(
            x=[1.0, 2.0],
            y=[3.0, 4.0],
            yerr=[0.2, 0.3],
            cap_size=5,
            key=["a", "b"],
        ),
        xy.animation(match="key"),
    ).figure()
    figure.traces[0].transition_keys = np.array(
        [[0, 0], [0x9E3779B9, 0x85EBCA6B]],
        dtype=np.uint32,
    )

    with pytest.raises(ValueError, match="role-qualified animation key collision"):
        figure.build_payload()


def test_key_count_mismatch_records_index_fallback() -> None:
    figure = xy.scatter_chart(
        xy.scatter(x=[1.0, 2.0], y=[3.0, 4.0], key=["a", "b"]),
        xy.animation(match="key"),
    ).figure()
    transition_keys = figure.traces[0].transition_keys
    assert transition_keys is not None
    figure.traces[0].transition_keys = transition_keys[:1]

    spec, _ = figure.build_payload()

    trace = spec["traces"][0]
    assert trace["animation_fallback"] == "index:key-count-mismatch"
    assert "keys" not in trace


def test_static_exports_ignore_motion_and_html_can_freeze_progress() -> None:
    plain = xy.line_chart(xy.line(x=[0.0, 1.0], y=[1.0, 2.0]))
    animated = xy.line_chart(
        xy.line(x=[0.0, 1.0], y=[1.0, 2.0]),
        xy.animation(enabled=True, enter="reveal"),
    )

    assert animated.to_svg() == plain.to_svg()
    live_html = animated.to_html()
    middle_html = animated.to_html(animation_progress=0.5)
    end_html = animated.to_html(animation_progress=1.0)
    assert '"animation_capture_progress":' not in live_html
    assert '"animation_capture_progress":0.5' in middle_html
    assert '"animation_capture_progress":1.0' in end_html
    with pytest.raises(ValueError, match="animation progress"):
        animated.to_html(animation_progress=1.1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"enabled": "yes"},
        {"duration": -1},
        {"easing": "bounce"},
        {"easing": (1.2, 0.0, 0.5, 1.0)},
        {"match": "name"},
        {"enter": "fly"},
        {"enter": "fade"},
        {"enter": "fade-scale"},
        {"update": "crossfade"},
        {"interpolate": ["opacity"]},
        {"interpolate": ["position", "position"]},
    ],
)
def test_animation_validation(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="animation"):
        xy.animation(**kwargs)


def test_exit_is_not_a_supported_animation_option() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument 'exit'"):
        xy.animation(**{"exit": "fade"})


# --- stable-key encoding: same answers, without the per-row dictionaries -----


def test_transition_key_digests_are_stable_and_row_aligned() -> None:
    """Encoding is a pure per-row hash: order-independent and reproducible."""
    from xy.components import _encode_transition_keys

    keys = ["a", "b", "c", "d"]
    first = _encode_transition_keys(keys, 4, "keys")
    assert first.dtype == np.uint32 and first.shape == (4, 2)
    np.testing.assert_array_equal(first, _encode_transition_keys(keys, 4, "keys"))
    # Row i's digest depends only on key i, so permuting the input permutes the
    # output rows and nothing else.
    shuffled = _encode_transition_keys(["c", "a", "d", "b"], 4, "keys")
    np.testing.assert_array_equal(shuffled, first[[2, 0, 3, 1]])
    # Distinct keys must give distinct digests, which is what the vectorized
    # uniqueness check the encoder now relies on is asserting.
    assert len({tuple(row) for row in first}) == 4


@pytest.mark.parametrize(
    "keys",
    [
        ["a", "b", "a"],
        [1, 2, 1],
        [1.5, 2.5, 1.5],
        [True, False, True],
        [b"x", b"y", b"x"],
    ],
    ids=["str", "int", "float", "bool", "bytes"],
)
def test_duplicate_transition_keys_name_both_rows(keys: list) -> None:
    """The duplicate message still names the first and second offending rows.

    The encoder no longer keeps a token dictionary while hashing; a conflict is
    re-walked to produce this message, so it must be unchanged.
    """
    from xy.components import _encode_transition_keys

    with pytest.raises(ValueError, match=r"keys contains duplicate value at rows 0 and 2"):
        _encode_transition_keys(keys, 3, "keys")


def test_transition_key_type_errors_still_report_their_row() -> None:
    from xy.components import _encode_transition_keys

    with pytest.raises(ValueError, match="animation key is missing at row 1"):
        _encode_transition_keys(["a", None, "c"], 3, "keys")
    with pytest.raises(ValueError, match="animation key must be finite at row 2"):
        _encode_transition_keys([1.0, 2.0, float("nan")], 3, "keys")
    with pytest.raises(ValueError, match="row 1 has list"):
        _encode_transition_keys(["a", [], "c"], 3, "keys")


@pytest.mark.parametrize("n_good", [1, 2, 3, 17])
def test_a_short_fallback_prefix_is_packable(n_good: int) -> None:
    """Date keys always take the Python fallback, so this reaches the prefix
    digest test at tiny lengths — where the Fortran-order buffer bites.

    `result[:1]` is a one-row slice of an F-order (N, 2) array, and numpy can
    satisfy `reshape(-1)` on it with a strided *view*; re-viewing that as uint64
    raises "the last axis must be contiguous", replacing the key error with a
    numpy internal one. The digests are packed from the two columns instead.
    """
    from xy.components import _encode_transition_keys

    keys: list = [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(n_good)]
    encoded = _encode_transition_keys(keys, n_good, "keys")
    assert encoded.shape == (n_good, 2)
    assert encoded[:, 0].flags.c_contiguous and encoded[:, 1].flags.c_contiguous

    # ...and the error path, which packs the completed prefix before re-raising.
    with pytest.raises(ValueError, match=f"animation key is missing at row {n_good}"):
        _encode_transition_keys([*keys, None], n_good + 1, "keys")
    # ...and with a duplicate inside that prefix, which must win instead.
    if n_good >= 2:
        dup = [keys[0], *keys[:-1], None]
        with pytest.raises(ValueError, match=r"keys contains duplicate value at rows 0 and 1"):
            _encode_transition_keys(dup, len(dup), "keys")


@pytest.mark.parametrize(
    ("keys", "rows"),
    [
        pytest.param(["a", "a", None], (0, 1), id="missing"),
        pytest.param([1.0, 1.0, float("nan")], (0, 1), id="non-finite"),
        pytest.param(["a", "a", {}], (0, 1), id="wrong-type"),
        pytest.param(["a", "b", "a", None], (0, 2), id="later-duplicate"),
    ],
)
def test_a_duplicate_outranks_a_later_invalid_row(keys: list, rows: tuple[int, int]) -> None:
    """First bad row wins, whichever kind of bad it is.

    The uniqueness test runs after the walk, so a duplicate would otherwise be
    reported only once every later row had tokenized — and any invalid row
    behind it would mask the duplicate entirely. Both inputs are wrong twice
    over; which error surfaces is the contract.
    """
    from xy.components import _encode_transition_keys

    expected = f"keys contains duplicate value at rows {rows[0]} and {rows[1]}"
    with pytest.raises(ValueError, match=re.escape(expected)):
        _encode_transition_keys(keys, len(keys), "keys")


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (0, 1),  # both in the first block
        (0, 4095),  # first block, at its last row
        (0, 4096),  # spans the first block boundary
        (4095, 4096),  # straddles it
        (4096, 4097),  # both in the second block
        (0, 32768),  # spans the second boundary (stride x8)
        (5000, 40000),  # neither in the first block, different blocks
        (0, 49999),  # last row of all
    ],
)
def test_a_duplicate_is_named_the_same_wherever_the_block_boundaries_fall(
    first: int, second: int
) -> None:
    """Uniqueness is tested on growing prefixes, so a duplicate whose two rows
    land in different blocks must still be reported — and reported with the same
    two row numbers a single trailing test would have produced."""
    from xy.components import _encode_transition_keys

    n = 50_000
    keys = [f"k-{i:09d}" for i in range(n)]
    keys[second] = keys[first]
    expected = f"keys contains duplicate value at rows {first} and {second}"
    with pytest.raises(ValueError, match=re.escape(expected)):
        _encode_transition_keys(keys, n, "keys")


def test_prefix_checks_do_not_change_the_encoding() -> None:
    """The blocked walk must produce the same digests as one straight pass, at
    sizes below, at, and above the first block boundary."""
    from xy.components import _encode_transition_keys

    for n in (1, 4095, 4096, 4097, 32769, 40000):
        keys = [f"k-{i:09d}" for i in range(n)]
        got = _encode_transition_keys(keys, n, "keys")
        assert got.shape == (n, 2) and got.dtype == np.uint32
        # Every row is an independent hash of its own key, so a one-row encode
        # of key i must equal row i of the bulk encode.
        for probe in {0, n // 2, n - 1}:
            single = _encode_transition_keys([keys[probe]], 1, "keys")
            np.testing.assert_array_equal(single[0], got[probe])


def test_the_superseded_token_error_is_not_chained_onto_the_duplicate() -> None:
    """The prefix re-check runs inside an `except`, so without suppression the
    error it deliberately discards would print *first*, above a 'During handling
    of the above exception' banner — the traceback would lead with the one
    message this is not supposed to report."""
    import traceback

    from xy.components import _encode_transition_keys

    try:
        _encode_transition_keys(["a", "a", None], 3, "keys")
    except ValueError as exc:
        assert exc.__context__ is None or exc.__suppress_context__
        rendered = "".join(traceback.format_exception(exc))
        assert "During handling of the above exception" not in rendered
        assert "is missing at row 2" not in rendered
        assert "keys contains duplicate value at rows 0 and 1" in rendered
    else:  # pragma: no cover
        raise AssertionError("expected a duplicate-key error")


def test_a_duplicate_outranks_a_non_valueerror_token_failure() -> None:
    """Which row was first cannot depend on which exception the token raised.

    A key type whose `encode` raises something other than ValueError must not
    smuggle a later row's failure past an earlier duplicate.
    """
    from xy.components import _encode_transition_keys

    class BadStr(str):
        def encode(self, *args: object, **kwargs: object) -> bytes:
            raise RuntimeError("boom-encode")

    with pytest.raises(ValueError, match="keys contains duplicate value at rows 0 and 1"):
        _encode_transition_keys(["a", "a", BadStr("z")], 3, "keys")
    # With no earlier duplicate the original failure still propagates untouched.
    with pytest.raises(RuntimeError, match="boom-encode"):
        _encode_transition_keys(["a", "b", BadStr("z")], 3, "keys")


def test_an_invalid_row_before_a_duplicate_still_wins() -> None:
    """The converse: nothing about the prefix re-check promotes a later
    duplicate over an earlier bad row."""
    from xy.components import _encode_transition_keys

    with pytest.raises(ValueError, match="animation key is missing at row 0"):
        _encode_transition_keys([None, "a", "a"], 3, "keys")


def test_transition_keys_length_and_shape_are_validated() -> None:
    from xy.components import _encode_transition_keys

    with pytest.raises(ValueError, match="must have length 4"):
        _encode_transition_keys(["a", "b"], 4, "keys")
    with pytest.raises(ValueError, match="must be one-dimensional"):
        _encode_transition_keys([["a"], ["b"]], 2, "keys")
    assert _encode_transition_keys([], 0, "keys").shape == (0, 2)
