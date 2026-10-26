"""Benchmark the data-bound chart tier's page-time and serve-time costs.

The plan tier moves work to two places the rest of the benchmark program
does not cover: page evaluation (every chart factory call compiles + probes
a plan) and backend-worker startup (`_ensure_page_plans` re-evaluates every
page). Both must stay compile-scale (milliseconds), and a column republish
must stay dominated by the figure build it fans out, or the tier's promise
("state deltas independent of data size, republish = one screen-bounded
reship") quietly erodes. That last promise is a *scaling* claim, so
republish is measured as a sweep over data size rather than at one N: a
single number at a single N is consistent with any growth curve and reveals
none of them. This harness measures all of it reproducibly;
recorded results live in spec/design/reflex-integration.md §6.

Run (needs the reflex extra):

    uv run python scripts/bench_reflex_plans.py [--json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import tracemalloc
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

REPEATS = 30
STARTUP_PAGES = 20
CHARTS_PER_PAGE = 4

#: Republish is measured as a *sweep*, not at one size. The property under
#: test — "state deltas are independent of data size; a republish is one
#: screen-bounded reship" — is a scaling claim, and a single datum at a
#: single N is consistent with O(N) without ever revealing it. The sweep
#: straddles `SCATTER_DENSITY_THRESHOLD` (200k) deliberately: below it every
#: republish rebuilds a full exact-marker figure, above it the density tier
#: takes over, and the two regimes have to be visible separately. Repeats
#: shrink with N to keep the whole run interactive.
REPUBLISH_SWEEP = (
    (10_000, 25),
    (100_000, 15),
    (1_000_000, 9),
    (2_000_000, 7),
    (5_000_000, 5),
)
REPUBLISH_REFERENCE_POINTS = 100_000

#: Each size is measured over several independent trials, and the sweep
#: reports the spread across them alongside the median. Run-to-run variance at
#: the top of the sweep is comparable to the differences between neighbouring
#: sizes, so a single median per size cannot distinguish a real trend from
#: noise — and reading a lone high point as a trend is exactly the mistake the
#: recorded table is there to prevent.
REPUBLISH_TRIALS = 3


def _median_ms(fn: Callable[[], Any], repeats: int = REPEATS) -> float:
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1e3)
    return statistics.median(times)


def bench_plan_build() -> float:
    """One flat factory call at page evaluation (compile + probe + digest)."""
    import xy
    from reflex_xy.plan import build_plan, reset_plans_for_tests

    def build() -> None:
        reset_plans_for_tests()  # avoid the map turning builds into lookups
        build_plan(
            "scatter_chart",
            (xy.scatter("x", "y", color="mag", colormap="viridis"), xy.x_axis(label="sigma")),
            {"title": "cloud"},
        )

    return _median_ms(build)


def bench_worker_startup() -> float:
    """_ensure_page_plans over a synthetic app: pages x charts per worker boot."""
    import reflex_xy
    from reflex_xy.app import _ensure_page_plans
    from reflex_xy.handles import DataHandle
    from reflex_xy.plan import reset_plans_for_tests

    def page(i: int) -> Callable[[], Any]:
        def body() -> Any:
            # live tier (DataHandle): the page cost is plan compile + probe +
            # component mount, with no payload-asset writes involved
            return [
                reflex_xy.chart(
                    reflex_xy.scatter("x", "y", opacity=0.4 + 0.001 * (i * CHARTS_PER_PAGE + j)),
                    data=DataHandle(""),
                )
                for j in range(CHARTS_PER_PAGE)
            ]

        return body

    app = SimpleNamespace(
        _unevaluated_pages={
            f"page{i}": SimpleNamespace(component=page(i)) for i in range(STARTUP_PAGES)
        }
    )

    def boot() -> None:
        reset_plans_for_tests()
        _ensure_page_plans(app)

    return _median_ms(boot, repeats=5)


def _republish_at(points: int, repeats: int) -> float:
    """publish_columns -> dependent bind + figure build + publish, mounted."""
    import warnings

    import numpy as np

    import xy
    from reflex_xy.plan import build_plan
    from reflex_xy.registry import FigureRegistry
    from reflex_xy.tokens import build_plan_token

    registry = FigureRegistry()
    plan = build_plan("scatter_chart", (xy.scatter("x", "y"),), {})
    data_token = f"xyd1|bench-client-token|app.app.State|cloud{points}"
    composite = build_plan_token(plan.digest, data_token)
    registry.subscribe(composite, "bench-sid", rebuildable=True)
    registry.bind_plan(data_token, plan.digest)
    rng = np.random.default_rng(7)
    xs = rng.normal(size=points)
    columns = {"x": xs, "y": xs * 0.5}

    def republish() -> None:
        registry.publish_columns(data_token, columns)

    with warnings.catch_warnings():
        # Above the direct soft ceiling xy renders a density surface and says
        # so. That regime change is what the top of the sweep is *for*, so the
        # notice is expected here rather than a finding.
        warnings.filterwarnings("ignore", message=".*soft ceiling.*")
        republish()  # prime the mount
        return _median_ms(republish, repeats=repeats)


def bench_republish_sweep() -> list[dict[str, float]]:
    """Republish cost across data sizes, with per-million-point normalization.

    `ms_per_million` settling into a band as N grows means the cost is
    dominated by the per-point figure build and nothing worse than linear has
    crept in. The regression this exists to catch is that normalized value
    climbing *clear of the band* at the top of the sweep — `ms_per_million_min`
    and `_max` are reported so the band is visible and a single high median is
    not mistaken for a trend.
    """
    rows: list[dict[str, float]] = []
    for points, repeats in REPUBLISH_SWEEP:
        trials = [_republish_at(points, repeats) for _ in range(REPUBLISH_TRIALS)]
        per_million = sorted(ms * 1e6 / points for ms in trials)
        rows.append(
            {
                "points": points,
                "republish_ms": round(statistics.median(trials), 2),
                "ms_per_million": round(statistics.median(per_million), 2),
                "ms_per_million_min": round(per_million[0], 2),
                "ms_per_million_max": round(per_million[-1], 2),
            }
        )
    return rows


def bench_plan_memory() -> float:
    """Resident bytes per registered plan (the worker-lifetime map entry)."""
    import xy
    from reflex_xy.plan import build_plan, reset_plans_for_tests

    reset_plans_for_tests()
    count = 200
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    for i in range(count):
        build_plan("scatter_chart", (xy.scatter("x", "y", opacity=i / count),), {})
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    total = sum(stat.size_diff for stat in after.compare_to(before, "filename"))
    reset_plans_for_tests()
    return total / count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    sweep = bench_republish_sweep()
    reference = next(
        (row for row in sweep if row["points"] == REPUBLISH_REFERENCE_POINTS), sweep[0]
    )
    results = {
        "plan_build_ms": round(bench_plan_build(), 3),
        "worker_startup_ms": round(bench_worker_startup(), 1),
        "worker_startup_pages": STARTUP_PAGES,
        "worker_startup_charts": STARTUP_PAGES * CHARTS_PER_PAGE,
        "republish_sweep": sweep,
        "republish_ms": reference["republish_ms"],
        "republish_points": reference["points"],
        "plan_memory_bytes": round(bench_plan_memory()),
    }
    if args.json:
        print(json.dumps(results, indent=2))
        return 0
    print(f"plan build (compile+probe+digest)  {results['plan_build_ms']:8.3f} ms median")
    print(
        f"worker startup page evaluation     {results['worker_startup_ms']:8.1f} ms "
        f"({STARTUP_PAGES} pages x {CHARTS_PER_PAGE} charts)"
    )
    print(f"column republish -> new payload (mounted, median of {REPUBLISH_TRIALS} trials):")
    for row in sweep:
        print(
            f"  {int(row['points']):>10,} points          {row['republish_ms']:8.2f} ms "
            f"({row['ms_per_million']:5.2f} ms / 1M points, "
            f"{row['ms_per_million_min']:.2f}-{row['ms_per_million_max']:.2f} across trials)"
        )
    print(f"plan map entry                     {results['plan_memory_bytes']:8.0f} bytes/plan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
