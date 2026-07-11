from __future__ import annotations

from types import SimpleNamespace

from benchmarks import bench_pyplot_vs_matplotlib as bench


def test_summary_uses_median_and_retains_tail_latency() -> None:
    samples = [
        {"build_ms": 1.0, "render_ms": 9.0, "total_ms": 10.0, "output_bytes": 100},
        {"build_ms": 2.0, "render_ms": 10.0, "total_ms": 12.0, "output_bytes": 120},
        {"build_ms": 3.0, "render_ms": 17.0, "total_ms": 20.0, "output_bytes": 140},
    ]

    summary = bench._summary(samples)

    assert summary == {
        "build_median_ms": 2.0,
        "render_median_ms": 10.0,
        "total_median_ms": 12.0,
        "total_p95_ms": 20.0,
        "output_bytes_median": 120,
    }


def test_profiles_include_huge_for_large_n_claims() -> None:
    assert bench.PROFILE_NAMES == ("smoke", "standard", "huge")


def test_comparison_carries_xy_render_tier() -> None:
    case = SimpleNamespace(family="scatter", label="1M points", work_units=10**6, unit="points")
    xy_row = {
        "build_median_ms": 1.0,
        "render_median_ms": 9.0,
        "total_median_ms": 10.0,
        "output_bytes_median": 200,
        "render_tier": "density",
    }
    matplotlib_row = {
        "build_median_ms": 2.0,
        "render_median_ms": 18.0,
        "total_median_ms": 20.0,
        "output_bytes_median": 100,
    }

    comparison = bench._compare(case, xy_row, matplotlib_row, target_speedup=10.0)

    assert comparison["xy_render_tier"] == "density"


def test_comparison_defines_speedup_as_matplotlib_over_xy() -> None:
    case = SimpleNamespace(family="scatter", label="100 points", work_units=100, unit="points")
    xy_row = {
        "build_median_ms": 1.0,
        "render_median_ms": 9.0,
        "total_median_ms": 10.0,
        "output_bytes_median": 200,
    }
    matplotlib_row = {
        "build_median_ms": 2.0,
        "render_median_ms": 18.0,
        "total_median_ms": 20.0,
        "output_bytes_median": 100,
    }

    comparison = bench._compare(case, xy_row, matplotlib_row, target_speedup=10.0)

    assert comparison["xy_speedup_total"] == 2.0
    assert comparison["target_xy_speedup_total"] == 10.0
    assert comparison["meets_target"] is False
    assert comparison["winner_total"] == "xy.pyplot"
    assert comparison["png_size_ratio_matplotlib_over_xy"] == 0.5


def test_png_dimension_oracle_reads_ihdr() -> None:
    png = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (1800).to_bytes(4, "big")
        + (840).to_bytes(4, "big")
    )

    assert bench._png_dimensions(png) == (1800, 840)
