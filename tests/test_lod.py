from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fastcharts import lod

ROOT = Path(__file__).resolve().parents[1]


def test_viewport_request_normalizes_ranges_and_clamps_screen_shape() -> None:
    request = lod.ViewportRequest.from_client(10.0, -2.0, 5.0, 1.0, 0, 10_000)

    assert request.x_range == (-2.0, 10.0)
    assert request.y_range == (1.0, 5.0)
    assert request.width == 16
    assert request.height > 16


def test_viewport_request_rejects_bad_bounds_and_screen_shape() -> None:
    with pytest.raises(ValueError, match="view window"):
        lod.ViewportRequest.from_client(np.nan, 1.0, 0.0, 1.0, 64, 48)
    with pytest.raises(ValueError, match="screen dimensions"):
        lod.ViewportRequest.from_client(0.0, 1.0, 0.0, 1.0, True, 48)


def test_plan_view_lod_records_direct_and_aggregate_contract() -> None:
    request = lod.ViewportRequest.from_client(0.0, 100.0, 0.0, 100.0, 1200, 800)

    direct = lod.plan_view_lod(request, 100_000, 200_000, False)
    aggregate = lod.plan_view_lod(request, 350_000, 200_000, False)
    hysteresis = lod.plan_view_lod(request, 225_000, 200_000, True)
    drill_out = lod.plan_view_lod(request, 240_000, 200_000, True)

    assert direct.exact is True
    assert direct.metadata() == {
        "mode": "points",
        "tier": "direct",
        "visible": 100_000,
        "reduction": "none",
    }
    assert aggregate.exact is False
    assert aggregate.mode == "density"
    assert aggregate.tier == "density"
    assert aggregate.reduction == "count"
    assert aggregate.grid_w < request.width
    assert aggregate.grid_h < request.height
    assert hysteresis.exact is True
    assert drill_out.exact is False


def test_plan_view_lod_supports_non_scatter_representations() -> None:
    request = lod.ViewportRequest.from_client(0.0, 1.0, 0.0, 1.0, 512, 384)

    plan = lod.plan_view_lod(
        request,
        1_000_000,
        50_000,
        False,
        direct_mode="candles",
        aggregate_mode="ohlc-buckets",
        aggregate_reduction="first-max-min-last",
    )

    assert plan.metadata() == {
        "mode": "ohlc-buckets",
        "tier": "ohlc-buckets",
        "visible": 1_000_000,
        "reduction": "first-max-min-last",
    }


def test_scatter_density_view_routes_through_shared_lod_primitives(monkeypatch) -> None:
    from fastcharts import interaction
    from fastcharts._figure import Figure

    calls: dict[str, list[object]] = {
        "request": [],
        "plan": [],
        "encode": [],
        "enter": [],
        "exit": [],
    }
    original_from_client = interaction.lod.ViewportRequest.from_client
    original_plan = interaction.lod.plan_view_lod
    original_encode = interaction.lod.encode_window_xy_columns
    original_enter = interaction.lod.enter_drill
    original_exit = interaction.lod.exit_drill

    def wrapped_from_client(cls, *args, **kwargs):
        calls["request"].append(args)
        return original_from_client(*args, **kwargs)

    def wrapped_plan(*args, **kwargs):
        plan = original_plan(*args, **kwargs)
        calls["plan"].append(plan)
        return plan

    def wrapped_encode(*args, **kwargs):
        calls["encode"].append(args)
        return original_encode(*args, **kwargs)

    def wrapped_enter(trace, sel):
        calls["enter"].append(int(len(sel)))
        return original_enter(trace, sel)

    def wrapped_exit(trace):
        calls["exit"].append(bool(trace.drill_mode))
        return original_exit(trace)

    monkeypatch.setattr(
        interaction.lod.ViewportRequest,
        "from_client",
        classmethod(wrapped_from_client),
    )
    monkeypatch.setattr(interaction.lod, "plan_view_lod", wrapped_plan)
    monkeypatch.setattr(interaction.lod, "encode_window_xy_columns", wrapped_encode)
    monkeypatch.setattr(interaction.lod, "enter_drill", wrapped_enter)
    monkeypatch.setattr(interaction.lod, "exit_drill", wrapped_exit)
    monkeypatch.setattr(interaction, "SCATTER_DENSITY_THRESHOLD", 80)
    monkeypatch.setattr(interaction, "PYRAMID_MIN_POINTS", 1_000_000)

    x = np.linspace(0.0, 99.0, 500)
    y = np.sin(x / 8.0) + x / 100.0
    fig = Figure().scatter(x, y, density=True)

    wide, _ = fig.density_view(0, 0.0, 99.0, -2.0, 2.0, 320, 240)
    drilled, _ = fig.density_view(0, 0.0, 4.0, -2.0, 2.0, 320, 240)
    wide_again, _ = fig.density_view(0, 0.0, 99.0, -2.0, 2.0, 320, 240)

    assert wide["traces"][0]["mode"] == "density"
    assert drilled["traces"][0]["mode"] == "points"
    assert wide_again["traces"][0]["mode"] == "density"
    assert len(calls["request"]) == 3
    assert any(plan.exact is False for plan in calls["plan"])
    assert any(plan.exact is True for plan in calls["plan"])
    assert len(calls["encode"]) >= 2
    assert calls["enter"] == [drilled["traces"][0]["visible"]]
    assert True in calls["exit"]


def test_density_view_rejects_bad_viewport_before_mutating_drill_state(monkeypatch) -> None:
    from fastcharts import interaction
    from fastcharts._figure import Figure

    monkeypatch.setattr(interaction, "SCATTER_DENSITY_THRESHOLD", 80)
    monkeypatch.setattr(interaction, "PYRAMID_MIN_POINTS", 1_000_000)

    x = np.linspace(0.0, 99.0, 500)
    y = np.sin(x / 8.0) + x / 100.0
    fig = Figure().scatter(x, y, density=True)
    trace = fig.traces[0]

    drilled, _ = fig.density_view(0, 0.0, 4.0, -2.0, 2.0, 320, 240)
    shipped_before = trace.shipped_sel.copy()
    seq_before = trace.drill_seq

    with pytest.raises(ValueError, match="view window"):
        fig.density_view(0, np.nan, 99.0, -2.0, 2.0, 320, 240)

    assert drilled["traces"][0]["mode"] == "points"
    assert trace.drill_mode is True
    assert trace.drill_seq == seq_before
    np.testing.assert_array_equal(trace.shipped_sel, shipped_before)


def test_line_area_decimate_view_routes_through_shared_buffer_writer(monkeypatch) -> None:
    from fastcharts import interaction
    from fastcharts._figure import Figure
    from fastcharts.config import DECIMATION_THRESHOLD

    calls: list[dict[str, object]] = []
    original_writer = interaction.lod.BufferWriter

    class SpyWriter(original_writer):
        def add_encoded(self, column):  # type: ignore[no-untyped-def]
            calls.append({"len": column.length, "meta": dict(column.meta)})
            return super().add_encoded(column)

    monkeypatch.setattr(interaction.lod, "BufferWriter", SpyWriter)

    n = DECIMATION_THRESHOLD + 1
    x = np.arange(n, dtype=np.float64)
    y = np.sin(x * 0.01)
    base = y - 2.0
    fig = Figure().area(x, y, base=base)

    update, buffers = fig.decimate_view(200.0, 800.0, 128)
    trace = update["traces"][0]

    assert [trace["x"]["buf"], trace["y"]["buf"], trace["base"]["buf"]] == [0, 1, 2]
    assert len(calls) == 3
    assert len(buffers) == 3
    assert all(call["len"] == trace["x"]["len"] for call in calls)
    assert {"offset", "scale"} <= set(calls[0]["meta"])


def test_lod_architecture_doc_names_shared_extension_points() -> None:
    text = (ROOT / "docs" / "design" / "lod-architecture.md").read_text(encoding="utf-8")

    for marker in (
        "ViewportRequest.from_client",
        "plan_view_lod",
        "encode_window_xy_columns",
        "add_window_xy",
        "BufferWriter.add_encoded",
        "sample_rows_for_target",
        "Line and area zoom",
        "local_log_density",
        "ohlc-buckets",
        "box-buckets",
        "T6",
        "invalid requests do not mutate",
    ):
        assert marker in text


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"visible": -1}, "visible"),
        ({"budget": 0.0}, "LOD budget"),
        ({"in_drill": "yes"}, "in_drill"),
        ({"aggregate_mode": ""}, "aggregate_mode"),
    ],
)
def test_plan_view_lod_rejects_bad_options(kwargs, message: str) -> None:
    request = lod.ViewportRequest.from_client(0.0, 1.0, 0.0, 1.0, 64, 48)
    options = {"visible": 10, "budget": 100.0, "in_drill": False} | kwargs

    with pytest.raises(ValueError, match=message):
        lod.plan_view_lod(request, **options)


def test_encode_f32_values_and_buffer_writer_share_wire_contract() -> None:
    offset = 1e300
    values = np.array([offset - 1e290, offset, offset + 1e290], dtype=np.float64)

    column = lod.encode_f32_values(
        values,
        offset,
        offset - 1e290,
        offset + 1e290,
        kind="float",
    )
    writer = lod.BufferWriter()
    ref = writer.add_encoded(column)

    assert column.length == 3
    assert column.values.dtype == np.float32
    assert np.isfinite(column.values).all()
    assert column.meta["offset"] == offset
    assert column.meta["scale"] == pytest.approx(1e-253)
    assert column.meta["kind"] == "float"
    assert ref == {"buf": 0, "len": 3, **column.meta}
    assert len(writer.buffers) == 1


def test_add_window_xy_uses_single_shared_buffer_writer_contract() -> None:
    xs = np.array([9.0, 10.0, 11.0], dtype=np.float64)
    ys = np.array([98.0, 100.0, 102.0], dtype=np.float64)
    writer = lod.BufferWriter()

    x_ref, y_ref = lod.add_window_xy(writer, xs, ys, 0.0, 20.0, 80.0, 120.0)

    assert [x_ref["buf"], y_ref["buf"]] == [0, 1]
    assert x_ref["len"] == 3
    assert y_ref["len"] == 3
    assert x_ref["offset"] == 10.0
    assert y_ref["offset"] == 100.0
    np.testing.assert_array_equal(
        np.frombuffer(writer.buffers[x_ref["buf"]], dtype=np.float32),
        np.array([-1.0, 0.0, 1.0], dtype=np.float32),
    )
    np.testing.assert_array_equal(
        np.frombuffer(writer.buffers[y_ref["buf"]], dtype=np.float32),
        np.array([-2.0, 0.0, 2.0], dtype=np.float32),
    )


def test_encode_f32_values_handles_empty_and_scalar_inputs() -> None:
    empty = lod.encode_f32_values([], 0.0, 0.0, 0.0)
    scalar = lod.encode_f32_values(42.0, 40.0, 40.0, 44.0)

    assert empty.length == 0
    assert empty.values.dtype == np.float32
    assert empty.meta == {"offset": 0.0, "scale": 1.0}
    assert scalar.length == 1
    assert scalar.values.tolist() == [2.0]


def test_sample_keep_mask_is_deterministic_and_monotonic_by_level() -> None:
    row_ids = np.arange(100_000, dtype=np.int64)

    level0 = lod.sample_keep_mask(row_ids, 0, base_fraction=1 / 2048, seed=11)
    level3 = lod.sample_keep_mask(row_ids, 3, base_fraction=1 / 2048, seed=11)
    level6 = lod.sample_keep_mask(row_ids, 6, base_fraction=1 / 2048, seed=11)

    assert np.array_equal(level3, lod.sample_keep_mask(row_ids, 3, base_fraction=1 / 2048, seed=11))
    assert np.all(level0 <= level3)
    assert np.all(level3 <= level6)
    assert 0 < int(level0.sum()) < int(level3.sum()) < int(level6.sum()) < len(row_ids)


def test_sample_keep_mask_is_row_order_independent() -> None:
    row_ids = np.array([42, 7, 99, 1234, 5, 8192, 65535, 17, 88, 300], dtype=np.uint64)
    forward = lod.sample_keep_mask(row_ids, 5, base_fraction=0.25, seed=3)
    reverse = lod.sample_keep_mask(row_ids[::-1], 5, base_fraction=0.25, seed=3)

    assert set(row_ids[forward]) == set(row_ids[::-1][reverse])


def test_sample_keep_mask_reaches_exact_mode_when_fraction_saturates() -> None:
    row_ids = np.arange(1024, dtype=np.int64)

    mask = lod.sample_keep_mask(row_ids, 20, base_fraction=1 / 1024, growth=2.0)

    assert mask.dtype == np.bool_
    assert mask.all()


def test_hash_row_ids_changes_with_seed_without_using_python_hash_order() -> None:
    row_ids = np.arange(512, dtype=np.uint64)

    a = lod.hash_row_ids(row_ids, seed=0)
    b = lod.hash_row_ids(row_ids, seed=1)

    assert a.dtype == np.uint64
    assert b.dtype == np.uint64
    assert np.array_equal(a, lod.hash_row_ids(row_ids, seed=0))
    assert not np.array_equal(a, b)


def test_stratified_sample_keep_mask_preserves_rare_categories_and_is_monotonic() -> None:
    row_ids = np.arange(8_104, dtype=np.int64)
    categories = np.array(["common"] * 8_000 + ["medium"] * 100 + ["rare"] * 4)

    level0 = lod.stratified_sample_keep_mask(
        row_ids,
        categories,
        0,
        base_fraction=1 / 4096,
        seed=23,
        min_per_category=1,
    )
    level5 = lod.stratified_sample_keep_mask(
        row_ids,
        categories,
        5,
        base_fraction=1 / 4096,
        seed=23,
        min_per_category=1,
    )

    assert np.all(level0 <= level5)
    assert int(level0[categories == "rare"].sum()) >= 1
    assert int(level0[categories == "medium"].sum()) >= 1
    assert int(level0[categories == "common"].sum()) >= 1
    assert int(level5.sum()) > int(level0.sum())
    assert int(level5[categories == "common"].sum()) < int((categories == "common").sum())


def test_stratified_sample_keep_mask_uses_stable_lowest_hash_floor() -> None:
    row_ids = np.arange(20, dtype=np.int64)
    categories = np.array(["a"] * 10 + ["b"] * 10)

    first = lod.stratified_sample_keep_mask(
        row_ids,
        categories,
        0,
        base_fraction=1 / 10_000,
        seed=4,
        min_per_category=2,
    )
    second = lod.stratified_sample_keep_mask(
        row_ids,
        categories,
        3,
        base_fraction=1 / 10_000,
        seed=4,
        min_per_category=2,
    )

    assert np.array_equal(first, second)
    assert int(first[categories == "a"].sum()) == 2
    assert int(first[categories == "b"].sum()) == 2


def test_sample_rows_for_target_is_order_independent_and_zoom_monotonic() -> None:
    row_ids = np.arange(10_000, dtype=np.uint32)

    broad = lod.sample_rows_for_target(row_ids, 64, seed=17)
    reordered = lod.sample_rows_for_target(row_ids[::-1], 64, seed=17)
    narrow_ids = row_ids[2_000:3_000]
    narrow = lod.sample_rows_for_target(narrow_ids, 64, seed=17)

    assert broad.dtype == row_ids.dtype
    assert set(broad.tolist()) == set(reordered.tolist())
    # Zooming into a subset raises the target fraction; any point already shown
    # in the overlap must remain instead of being replaced by a fresh random set.
    assert set(broad.tolist()) & set(narrow_ids.tolist()) <= set(narrow.tolist())


def test_sample_rows_for_target_saturates_without_reordering_rows() -> None:
    row_ids = np.array([9, 2, 7, 4], dtype=np.uint16)

    sampled = lod.sample_rows_for_target(row_ids, 99, seed=4)

    assert sampled.dtype == row_ids.dtype
    np.testing.assert_array_equal(sampled, row_ids)


def test_sample_rows_for_target_preserves_rare_categories_stably() -> None:
    row_ids = np.arange(1_003, dtype=np.uint32)
    categories = np.array(["common"] * 1_000 + ["rare"] * 3)
    order = np.r_[np.arange(500, 1_003), np.arange(0, 500)]

    sampled = lod.sample_rows_for_target(row_ids, 8, categories=categories, seed=19)
    reordered = lod.sample_rows_for_target(
        row_ids[order],
        8,
        categories=categories[order],
        seed=19,
    )

    assert set(sampled.tolist()) == set(reordered.tolist())
    assert set(sampled.tolist()) & set(row_ids[categories == "rare"].tolist())


@pytest.mark.parametrize(
    ("row_ids", "message"),
    [
        ([[1, 2], [3, 4]], "one-dimensional"),
        ([True, False], "integer array"),
        ([-1, 2], "negative"),
        ([1.0, 2.0], "integer array"),
    ],
)
def test_sample_keep_mask_rejects_bad_row_ids(row_ids, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        lod.sample_keep_mask(row_ids, 0)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"level": True}, "level"),
        ({"level": -1}, "level"),
        ({"base_fraction": 0.0}, "base_fraction"),
        ({"base_fraction": 1.1}, "base_fraction"),
        ({"growth": 0.5}, "growth"),
        ({"seed": True}, "seed"),
        ({"seed": 1 << 64}, "seed"),
    ],
)
def test_sample_keep_mask_rejects_bad_sampling_options(kwargs, message: str) -> None:
    options = {"level": 0, "base_fraction": 1 / 1024, "growth": 2.0, "seed": 0} | kwargs
    level = options.pop("level")

    with pytest.raises(ValueError, match=message):
        lod.sample_keep_mask(np.arange(10, dtype=np.int64), level, **options)


def test_stratified_sample_keep_mask_integer_fast_path_matches_labels() -> None:
    # Small non-negative integer categories skip np.unique and serve directly
    # as group codes (including a gap: code 2 is unused). The mask must be
    # bit-identical to the same categories spelled as string labels, which
    # take the np.unique dense-ranking path.
    rng = np.random.default_rng(17)
    row_ids = rng.permutation(4_000).astype(np.uint64)
    codes = rng.choice(np.array([0, 1, 3, 4]), size=4_000, p=[0.7, 0.2, 0.09, 0.01])
    labels = np.array(["a", "b", "d", "e"])[np.searchsorted([0, 1, 3, 4], codes)]

    for level, min_count in ((0, 1), (3, 2)):
        fast = lod.stratified_sample_keep_mask(
            row_ids, codes, level, base_fraction=1 / 512, seed=5, min_per_category=min_count
        )
        ranked = lod.stratified_sample_keep_mask(
            row_ids, labels, level, base_fraction=1 / 512, seed=5, min_per_category=min_count
        )
        assert np.array_equal(fast, ranked)
    # Negative codes must fall back to the np.unique path, not crash.
    negative = codes.astype(np.int64) - 5
    mask = lod.stratified_sample_keep_mask(row_ids, negative, 0, min_per_category=1)
    assert mask.shape == (4_000,)


def test_stratified_sample_keep_mask_rejects_mismatched_categories() -> None:
    with pytest.raises(ValueError, match="categories"):
        lod.stratified_sample_keep_mask(np.arange(3, dtype=np.int64), ["a", "b"], 0)

    with pytest.raises(ValueError, match="min_per_category"):
        lod.stratified_sample_keep_mask(
            np.arange(3, dtype=np.int64),
            ["a", "b", "c"],
            0,
            min_per_category=True,
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"target": 0}, "sample target"),
        ({"target": True}, "sample target"),
        ({"categories": ["a", "b"]}, "categories"),
    ],
)
def test_sample_rows_for_target_rejects_bad_options(kwargs, message: str) -> None:
    options = {"target": 4, "categories": None} | kwargs
    target = options.pop("target")

    with pytest.raises(ValueError, match=message):
        lod.sample_rows_for_target(np.arange(3, dtype=np.int64), target, **options)
