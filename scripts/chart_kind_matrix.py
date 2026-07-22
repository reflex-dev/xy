#!/usr/bin/env python3
"""Registry-complete payload and browser render matrix for every client mark."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "scripts"))

import xy  # noqa: E402
from _app_smoke import ChromiumSession, Probe, decode_png, find_chromium  # noqa: E402

VIEWPORT = (700, 420, 1.0)
MIN_COLORED_PIXELS = 20


@dataclass(frozen=True)
class Case:
    name: str
    expected_kinds: tuple[str, ...]
    mark: Callable[[], object]


CASES: tuple[Case, ...] = (
    Case("scatter", ("scatter",), lambda: xy.scatter([0, 1, 2], [0, 1, 0], color="#2563eb")),
    Case("line", ("line",), lambda: xy.line([0, 1, 2], [0, 1, 0], color="#dc2626", width=3)),
    Case("area", ("area",), lambda: xy.area([0, 1, 2], [1, 2, 1], color="#0891b2")),
    Case(
        "histogram", ("histogram",), lambda: xy.hist([0, 0.2, 0.4, 1, 1.2], bins=3, color="#7c3aed")
    ),
    Case(
        "box",
        ("box_whisker", "box", "box_median"),
        lambda: xy.box([1, 2, 2, 3, 5, 8], show_outliers=False, color="#ea580c"),
    ),
    Case(
        "violin", ("violin",), lambda: xy.violin([1, 2, 2, 3, 4, 5, 5, 6], bins=8, color="#16a34a")
    ),
    Case(
        "errorbar",
        ("errorbar",),
        lambda: xy.errorbar([0, 1, 2], [1, 2, 1], yerr=[0.2, 0.3, 0.2], color="#be123c"),
    ),
    Case(
        "stem",
        ("stem", "scatter"),
        lambda: xy.stem([0, 1, 2], [1, 2, 1], color="#0369a1", marker_size=8),
    ),
    Case(
        "segments",
        ("segments",),
        lambda: xy.segments([0, 1], [0, 1], [1, 2], [1, 0], color="#9333ea", width=4),
    ),
    Case(
        "triangle-mesh",
        ("triangle_mesh",),
        lambda: xy.triangle_mesh([0], [0], [1], [0], [0.5], [1], color=[0.7]),
    ),
    Case(
        "error-band",
        ("error_band",),
        lambda: xy.error_band([0, 1, 2], [0.8, 1.8, 0.8], [1.2, 2.2, 1.2], color="#0284c7"),
    ),
    Case(
        "hexbin",
        ("hexbin",),
        lambda: xy.hexbin([0, 0.1, 0.8, 0.9, 0.5], [0, 0.2, 0.8, 0.9, 0.5], gridsize=4, mincnt=1),
    ),
    Case("bar", ("bar",), lambda: xy.bar(["a", "b"], [1, 2], color="#4f46e5")),
    Case("column", ("column",), lambda: xy.column(["a", "b"], [2, 1], color="#0d9488")),
    Case("heatmap", ("heatmap",), lambda: xy.heatmap([[1, 2], [3, 4]])),
    Case(
        "contour",
        ("contour",),
        lambda: xy.contour([[0, 1, 0], [1, 2, 1], [0, 1, 0]], levels=3, color="#c026d3", width=3),
    ),
)


def shipped_registry() -> set[str]:
    program = (
        "import('./python/xy/static/index.js')"
        ".then(m=>console.log(JSON.stringify(Object.keys(m.MARK_KINDS).sort())))"
    )
    result = subprocess.run(
        ["node", "-e", program], cwd=ROOT, check=True, capture_output=True, text=True, timeout=30
    )
    return set(json.loads(result.stdout))


def validate_catalog(cases: Iterable[Case], registry: set[str]) -> None:
    cases = tuple(cases)
    names = [case.name for case in cases]
    if len(names) != len(set(names)):
        raise AssertionError("chart-kind case names must be unique")
    covered = {kind for case in cases for kind in case.expected_kinds}
    if covered != registry:
        raise AssertionError(
            f"chart-kind catalog mismatch: missing={sorted(registry - covered)}, "
            f"unexpected={sorted(covered - registry)}"
        )


def build_case(case: Case) -> tuple[object, dict, bytes]:
    chart = xy.scatter_chart(
        case.mark(),
        xy.x_axis(label="x"),
        xy.y_axis(label="y"),
        title=f"registry case: {case.name}",
        width=640,
        height=360,
    )
    spec, payload = chart.figure().build_payload(px_width=640)
    actual = tuple(trace["kind"] for trace in spec["traces"])
    if actual != case.expected_kinds:
        raise AssertionError(f"{case.name}: payload kinds {actual} != {case.expected_kinds}")
    for trace in spec["traces"]:
        if trace.get("tier") not in {"direct", "decimated", "density"}:
            raise AssertionError(f"{case.name}/{trace['kind']}: missing valid tier evidence")
        if int(trace.get("n_points", 0)) <= 0:
            raise AssertionError(f"{case.name}/{trace['kind']}: empty payload geometry")
    return chart, spec, payload


def colored_pixels(png: bytes, rect: dict[str, float]) -> int:
    width, height, channels, rgba = decode_png(png)
    left = max(0, int(rect["x"]))
    top = max(0, int(rect["y"]))
    right = min(width, int(rect["x"] + rect["w"]))
    bottom = min(height, int(rect["y"] + rect["h"]))
    count = 0
    for y in range(top, bottom):
        for x in range(left, right):
            pos = (y * width + x) * channels
            pixel = rgba[pos : pos + channels]
            red = pixel[0]
            green = pixel[1] if channels > 1 else red
            blue = pixel[2] if channels > 2 else red
            alpha = pixel[3] if channels == 4 else 255
            if alpha > 8 and max(red, green, blue) - min(red, green, blue) > 24:
                count += 1
    return count


def require_nonblank_pixels(name: str, count: int) -> None:
    if count < MIN_COLORED_PIXELS:
        raise AssertionError(f"{name}: blank/flat browser render ({count} colored pixels)")


def render_case(session: ChromiumSession, directory: Path, case: Case, chart: object) -> dict:
    document = chart.to_html()
    call = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'
    replacement = "window.__xyKindView = " + call
    if call not in document:
        raise AssertionError(f"{case.name}: standalone hydration call not found")
    page = directory / f"{case.name}.html"
    page.write_text(document.replace(call, replacement, 1), encoding="utf-8")
    probe = Probe(session, page.as_uri(), emulate=VIEWPORT)
    try:
        report = probe.wait_for(
            "(() => { const v=window.__xyKindView; if(!v||!v.gpuTraces) return null; "
            "v._drawNow(); return {kinds:v.gpuTraces.map(g=>g.trace.kind), "
            "counts:v.gpuTraces.map(g=>g.n||g.trace.n_points||0)}; })()",
            timeout_s=30,
            label=f"{case.name} GPU geometry",
        )
        if tuple(report["kinds"]) != case.expected_kinds:
            raise AssertionError(
                f"{case.name}: GPU kinds {report['kinds']} != {case.expected_kinds}"
            )
        if any(int(value) <= 0 for value in report["counts"]):
            raise AssertionError(f"{case.name}: empty GPU geometry {report['counts']}")
        pixels = colored_pixels(probe.screenshot(), probe.rect("[data-xy-slot='canvas']"))
        require_nonblank_pixels(case.name, pixels)
        return {
            "gpu_kinds": report["kinds"],
            "gpu_counts": report["counts"],
            "colored_pixels": pixels,
        }
    finally:
        probe.close()


def write_evidence(path: Path, evidence: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chromium", nargs="?")
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--evidence", type=Path, default=Path("chart-kind-matrix-evidence.json"))
    args = parser.parse_args(argv)

    registry = shipped_registry()
    validate_catalog(CASES, registry)
    evidence: dict = {"registry": sorted(registry), "cases": {}, "status": "failed"}
    try:
        built = [(case, *build_case(case)) for case in CASES]
        chromium = find_chromium(args.chromium)
        with (
            tempfile.TemporaryDirectory(prefix="xy-chart-kind-") as temp_dir,
            ChromiumSession(chromium, gl="software", sandbox=not args.no_sandbox) as session,
        ):
            for case, chart, spec, payload in built:
                browser = render_case(session, Path(temp_dir), case, chart)
                evidence["cases"][case.name] = {
                    "payload_kinds": [trace["kind"] for trace in spec["traces"]],
                    "payload_tiers": [trace["tier"] for trace in spec["traces"]],
                    "payload_bytes": len(payload),
                    **browser,
                }
        evidence["status"] = "passed"
        print(f"chart-kind matrix OK: {len(CASES)} cases cover {len(registry)} registry kinds")
        return 0
    except Exception as exc:
        evidence["error"] = str(exc)
        raise
    finally:
        write_evidence(args.evidence, evidence)


if __name__ == "__main__":
    raise SystemExit(main())
