from __future__ import annotations

import time

import benchmarks.bench_vs as bench_vs
import pytest


def test_run_marks_sizes_above_max_n_as_skipped(monkeypatch) -> None:
    monkeypatch.setattr(bench_vs, "ADAPTERS", {"fake": lambda _x, _y: None})

    report = bench_vs.run([10, 100], 45.0, libraries=["fake"], max_n=10)

    assert [row["status"] for row in report["results"]["fake"]] == [
        "unavailable",
        "skipped(over configured max-n)",
    ]


@pytest.mark.skipif(
    not hasattr(bench_vs.signal, "setitimer"),
    reason="hard benchmark deadlines require POSIX interval timers",
)
def test_run_enforces_budget_as_hard_measurement_timeout(monkeypatch) -> None:
    monkeypatch.setattr(
        bench_vs,
        "ADAPTERS",
        {"slow": lambda _x, _y: (lambda: None, lambda _fig: 0)},
    )

    def slow_measure(_build, _render, _artifact):
        time.sleep(1)
        raise AssertionError("the hard deadline did not interrupt the measurement")

    monkeypatch.setattr(bench_vs, "_measure", slow_measure)

    started = time.perf_counter()
    report = bench_vs.run([10, 100], 0.02, libraries=["slow"])
    elapsed = time.perf_counter() - started

    assert [row["status"] for row in report["results"]["slow"]] == [
        "skipped(hard timeout after 0.02s budget)",
        "skipped(over budget)",
    ]
    assert elapsed < 0.5


@pytest.mark.skipif(
    not hasattr(bench_vs.signal, "setitimer"),
    reason="hard benchmark deadlines require POSIX interval timers",
)
def test_hard_timeout_includes_browser_ttfr(monkeypatch) -> None:
    monkeypatch.setattr(
        bench_vs,
        "ADAPTERS",
        {"browser": lambda _x, _y: (lambda: None, lambda _fig: 0, lambda _fig: "html")},
    )
    monkeypatch.setattr(
        bench_vs,
        "_measure",
        lambda _build, _render, _artifact: {
            "build_s": 0.001,
            "render_s": 0.001,
            "total_s": 0.002,
            "peak_mem_mb": 1,
            "rss_delta_mb": 1,
            "out_bytes": 1,
            "artifact_s": 0.001,
            "_artifact": "html",
            "status": "ok",
            "mode": "direct",
            "render_target": "html",
            "oracle_status": "pass",
            "oracle_kind": "raw-row-count",
        },
    )

    def slow_browser(_html, *, chromium):
        time.sleep(1)
        raise AssertionError("the hard deadline did not interrupt browser TTFR")

    monkeypatch.setattr(bench_vs, "chart_ready_metrics", slow_browser)

    report = bench_vs.run([10], 0.02, libraries=["browser"], ttfr=True)

    assert report["results"]["browser"][0]["status"] == ("skipped(hard timeout after 0.02s budget)")


def test_run_only_captures_browser_artifact_within_ttfr_cap(monkeypatch) -> None:
    artifact_sizes: list[int] = []

    def factory(x, _y):
        def render(_fig):
            return {
                "out_bytes": 1,
                "mode": "direct",
                "render_target": "test",
                "oracle_status": "pass",
                "oracle_kind": "raw-row-count",
            }

        def artifact(_fig):
            artifact_sizes.append(len(x))
            return ""

        return lambda: None, render, artifact

    monkeypatch.setattr(bench_vs, "ADAPTERS", {"fake": factory})

    bench_vs.run([10, 100], 45, libraries=["fake"], ttfr=True, ttfr_max_n=10)

    assert artifact_sizes == [10]
