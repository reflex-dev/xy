"""Declarative animation and binary keyed-transition contracts."""

from __future__ import annotations

import json

import numpy as np
import pytest

import xy


def _column(blob: bytes | list[memoryview], spec: dict, index: int) -> np.ndarray:
    meta = spec["columns"][index]
    dtype = np.uint32 if meta.get("dtype") == "u32" else np.float32
    source = blob if isinstance(blob, bytes) else blob[meta["buf"]]
    return np.frombuffer(source, dtype=dtype, count=meta["len"], offset=meta["byte_offset"])


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


@pytest.mark.parametrize("layout", ["packed", "split"])
def test_shared_geometry_dedup_keeps_animation_keys_trace_local(layout: str) -> None:
    x = np.arange(6.0)
    keys = [f"row-{index}" for index in range(len(x))]
    chart = xy.chart(
        xy.scatter(x=x, y=x + 10.0, key=keys),
        xy.scatter(x=x, y=x + 20.0, key=keys),
        xy.animation(match="key"),
    )
    figure = chart.figure()
    spec, payload = figure.build_payload() if layout == "packed" else figure.build_payload_split()
    first, second = spec["traces"]

    assert first["x"] == second["x"]
    key_refs = [
        first["keys"]["lo"],
        first["keys"]["hi"],
        second["keys"]["lo"],
        second["keys"]["hi"],
    ]
    assert len(set(key_refs)) == 4
    assert len(spec["columns"]) == 7  # shared x + two y + four u32 key words
    first_pairs = list(
        zip(
            _column(payload, spec, first["keys"]["lo"]),
            _column(payload, spec, first["keys"]["hi"]),
            strict=True,
        )
    )
    second_pairs = list(
        zip(
            _column(payload, spec, second["keys"]["lo"]),
            _column(payload, spec, second["keys"]["hi"]),
            strict=True,
        )
    )
    assert first_pairs == second_pairs
    assert len(set(first_pairs)) == len(keys)


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
