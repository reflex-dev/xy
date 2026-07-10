from __future__ import annotations

import benchmarks.bench_vs as bench_vs


def test_run_marks_sizes_above_max_n_as_skipped(monkeypatch) -> None:
    monkeypatch.setattr(bench_vs, "ADAPTERS", {"fake": lambda _x, _y: None})

    report = bench_vs.run([10, 100], 45.0, libraries=["fake"], max_n=10)

    assert [row["status"] for row in report["results"]["fake"]] == [
        "unavailable",
        "skipped(over configured max-n)",
    ]
