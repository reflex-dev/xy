"""Benchmark the data-bound chart tier's page-time and serve-time costs.

The plan tier moves work to two places the rest of the benchmark program
does not cover: page evaluation (every chart factory call compiles + probes
a plan) and backend-worker startup (`_ensure_page_plans` re-evaluates every
page). Both must stay compile-scale (milliseconds), and a column republish
must stay dominated by the figure build it fans out, or the tier's promise
("state deltas independent of data size, republish = one screen-bounded
reship") quietly erodes. This harness measures all of it reproducibly;
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
REPUBLISH_POINTS = 100_000
STARTUP_PAGES = 20
CHARTS_PER_PAGE = 4


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


def bench_republish() -> float:
    """publish_columns -> dependent bind + figure build + publish, mounted."""
    import numpy as np

    import xy
    from reflex_xy.plan import build_plan
    from reflex_xy.registry import FigureRegistry
    from reflex_xy.tokens import build_plan_token

    registry = FigureRegistry()
    plan = build_plan("scatter_chart", (xy.scatter("x", "y"),), {})
    data_token = "xyd1|bench-client-token|app.app.State|cloud"
    composite = build_plan_token(plan.digest, data_token)
    registry.subscribe(composite, "bench-sid", rebuildable=True)
    registry.bind_plan(data_token, plan.digest)
    rng = np.random.default_rng(7)
    xs = rng.normal(size=REPUBLISH_POINTS)
    columns = {"x": xs, "y": xs * 0.5}

    def republish() -> None:
        registry.publish_columns(data_token, columns)

    republish()  # prime the mount
    return _median_ms(republish, repeats=10)


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

    results = {
        "plan_build_ms": round(bench_plan_build(), 3),
        "worker_startup_ms": round(bench_worker_startup(), 1),
        "worker_startup_pages": STARTUP_PAGES,
        "worker_startup_charts": STARTUP_PAGES * CHARTS_PER_PAGE,
        "republish_ms": round(bench_republish(), 1),
        "republish_points": REPUBLISH_POINTS,
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
    print(
        f"column republish -> new payload    {results['republish_ms']:8.1f} ms "
        f"({REPUBLISH_POINTS:,} points, mounted)"
    )
    print(f"plan map entry                     {results['plan_memory_bytes']:8.0f} bytes/plan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
