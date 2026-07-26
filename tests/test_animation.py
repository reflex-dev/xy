"""Declarative animation and binary keyed-transition contracts."""

from __future__ import annotations

import datetime as dt
import hashlib
import json

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


def test_aggregate_tier_records_key_matching_fallback() -> None:
    chart = xy.scatter_chart(
        xy.scatter(
            x=[1.0, 2.0, 3.0],
            y=[3.0, 4.0, 5.0],
            key=["a", "b", "c"],
            density=True,
            animation=xy.animation(duration=90),
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
