#!/usr/bin/env python3
"""Classify Plotly's attribute schema against what XY can express (§24).

§24 says compat should be "a measured number", and names Plotly's
`plot-schema.json` as the thing to ingest. Two facts about the world have
changed since that was written, and this script is written to both of them:

1. **No published Plotly wheel ships `plot-schema.json`.** Verified against
   4.14.3, 5.24.1, and 6.9.0 — the file is a plotly.js artifact and the Python
   package generates validator classes from it instead. The equivalent, and a
   better shape for this job, is `plotly/validators/_validators.json`: one flat
   entry per dotted attribute path with its validator class.
2. **XY has no Plotly shim.** The shipped shim is `xy.pyplot`, which is
   Matplotlib-flavored. So "supported" here cannot mean "the shim accepts the
   attribute" — there is nothing to accept it. It means *XY can express the
   same visual outcome*, and the rule that says so is committed below where it
   can be argued with.

Classification is rule-driven, not hand-enumerated: 9,472 attributes cannot be
audited one at a time, and a table that claims otherwise would be fiction. Each
rule names the XY surface that answers the attribute, so an unfamiliar reader
can check any row by following the pointer. Attributes no rule claims land in
`unsupported/unclassified`, which is the honest bucket — it is reported, never
folded into a friendlier one.

    uv run --extra bench python scripts/plotly_schema_coverage.py --check
    uv run --extra bench python scripts/plotly_schema_coverage.py --write
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "spec" / "api" / "plotly-coverage.md"

SUPPORTED = "supported"
MAPPED = "mapped-with-difference"
UNSUPPORTED = "unsupported"

#: Trace types XY implements, mapped to the XY mark that answers them. Every
#: other Plotly trace type is `unsupported/no-such-trace` — a truthful bucket,
#: and by far the largest one.
TRACE_EQUIVALENTS: dict[str, str] = {
    "scatter": "xy.scatter / xy.line",
    "scattergl": "xy.scatter",
    "bar": "xy.bar / xy.column",
    "histogram": "xy.histogram",
    "histogram2d": "xy.heatmap",
    "heatmap": "xy.heatmap",
    "box": "xy.box",
    "violin": "xy.violin",
    "contour": "xy.contour",
    "mesh3d": "",  # deliberately absent: 3-D is out of v1
}

#: Roots that are not trace types at all.
META_ROOTS = frozenset({"data", "frame", "frames"})


class Rule(NamedTuple):
    """One committed claim about a family of Plotly attributes."""

    pattern: str
    verdict: str
    surface: str
    note: str


#: Order matters: the first matching rule wins, so specific patterns precede
#: general ones. `*` matches within a path segment and across segments alike
#: (fnmatch semantics), which is what makes `*.marker.symbol` reach both
#: `scatter.marker.symbol` and `scatter.selected.marker.symbol`.
RULES: tuple[Rule, ...] = (
    # --- excluded subtrees, first because `*` spans dots ---------------------
    # `fnmatch` treats `*` as matching across `.`, and the first matching rule
    # wins, so `layout.*axis.showgrid` would otherwise claim
    # `layout.polar.angularaxis.showgrid` before the exclusion below could
    # reject it — silently counting 3-D, geo, polar, ternary, and smith axes as
    # supported and inflating the headline number. Order is load-bearing here.
    Rule("layout.scene*", UNSUPPORTED, "", "3-D is explicitly out of v1"),
    Rule("layout.geo*", UNSUPPORTED, "", "geo is explicitly out of v1"),
    Rule("layout.map*", UNSUPPORTED, "", "mapbox/map is explicitly out of v1"),
    Rule("layout.polar*", UNSUPPORTED, "", "polar axes are not implemented"),
    Rule("layout.ternary*", UNSUPPORTED, "", "ternary axes are not implemented"),
    Rule("layout.smith*", UNSUPPORTED, "", "smith axes are not implemented"),
    Rule("layout.updatemenus*", UNSUPPORTED, "", "no in-chart widget layer"),
    Rule("layout.sliders*", UNSUPPORTED, "", "no in-chart widget layer"),
    # --- paint and geometry XY draws exactly -------------------------------
    Rule("*.marker.symbol", SUPPORTED, "style={'marker-shape': ...}", "17 shared shapes"),
    Rule("*.marker.color", SUPPORTED, "color= / style={'fill': ...}", ""),
    Rule("*.marker.opacity", SUPPORTED, "style={'fill-opacity': ...}", ""),
    Rule("*.marker.size", SUPPORTED, "size=", ""),
    Rule("*.marker.line.color", SUPPORTED, "style={'stroke': ...}", ""),
    Rule("*.marker.line.width", SUPPORTED, "style={'stroke-width': ...}", ""),
    Rule("*.line.dash", SUPPORTED, "style={'stroke-dasharray': ...}", "named presets and px lists"),
    Rule("*.line.color", SUPPORTED, "style={'stroke': ...}", ""),
    Rule("*.line.width", SUPPORTED, "style={'stroke-width': ...}", ""),
    Rule("*.line.shape", MAPPED, "curve=", "XY has linear and monotone-cubic, not all six"),
    Rule("*.opacity", SUPPORTED, "style={'opacity': ...}", ""),
    Rule("*.name", SUPPORTED, "name=", ""),
    Rule("*.visible", MAPPED, "compose the chart without the mark", "no per-trace toggle prop"),
    Rule("*.colorscale", SUPPORTED, "colormap=", "custom ramps accepted"),
    Rule("*.showscale", SUPPORTED, "xy.colorbar()", ""),
    Rule("*.cmin", SUPPORTED, "color_domain=", ""),
    Rule("*.cmax", SUPPORTED, "color_domain=", ""),
    # --- layout XY answers --------------------------------------------------
    Rule("layout.xaxis.type", SUPPORTED, "xy.x_axis(scale=...)", ""),
    Rule("layout.yaxis.type", SUPPORTED, "xy.y_axis(scale=...)", ""),
    Rule("layout.*axis.title.text", SUPPORTED, "xy.x_axis(label=...)", ""),
    Rule("layout.*axis.range", SUPPORTED, "xy.x_axis(domain=...)", ""),
    Rule("layout.*axis.showgrid", SUPPORTED, "xy.x_axis(grid=...)", ""),
    Rule("layout.*axis.gridcolor", SUPPORTED, "style={'grid-color': ...}", ""),
    Rule("layout.*axis.gridwidth", SUPPORTED, "style={'grid-width': ...}", ""),
    Rule("layout.*axis.showline", SUPPORTED, "xy.x_axis(line=...)", ""),
    Rule("layout.*axis.linecolor", SUPPORTED, "style={'axis-color': ...}", ""),
    Rule("layout.*axis.ticklen", SUPPORTED, "style={'tick-length': ...}", ""),
    Rule("layout.*axis.tickcolor", SUPPORTED, "style={'tick-color': ...}", ""),
    Rule("layout.*axis.ticks", SUPPORTED, "style={'tick-direction': ...}", ""),
    Rule("layout.*axis.showticklabels", SUPPORTED, "xy.x_axis(text=...)", ""),
    Rule("layout.title.text", SUPPORTED, "title=", ""),
    Rule("layout.showlegend", SUPPORTED, "xy.legend()", ""),
    Rule("layout.legend.*", MAPPED, "xy.legend(...) + slot styling", "different option names"),
    Rule("layout.colorway", SUPPORTED, "xy.theme(palette=[...])", ""),
    Rule("layout.template", MAPPED, "xy.theme(...)", "not a serializable template format"),
    Rule("layout.paper_bgcolor", SUPPORTED, "style={'--chart-bg': ...}", ""),
    Rule("layout.plot_bgcolor", SUPPORTED, "style={'--chart-plot-bg': ...}", ""),
    Rule("layout.width", SUPPORTED, "width=", ""),
    Rule("layout.height", SUPPORTED, "height=", ""),
    Rule("layout.margin.*", SUPPORTED, "padding=", ""),
    Rule("layout.annotations.*", MAPPED, "xy.text() / xy.callout()", "different geometry model"),
    Rule("layout.shapes.*", MAPPED, "xy.rule() / xy.band()", "no arbitrary path shapes"),
    Rule("layout.hovermode", MAPPED, "xy.tooltip(...)", ""),
    Rule("layout.dragmode", MAPPED, "xy.modebar(...) / interaction options", ""),
    Rule("layout.transition*", MAPPED, "xy.animation(...)", "different easing vocabulary"),
    Rule("*.hovertemplate", MAPPED, "xy.tooltip(...)", "not a mini-language"),
    Rule("*.customdata", MAPPED, "tooltip sources", ""),
)


def load_schema() -> tuple[dict[str, dict], str]:
    """The installed plotly's flat validator schema, and its version."""
    try:
        import plotly
    except ModuleNotFoundError:  # pragma: no cover - depends on the extra
        raise SystemExit(
            "plotly is not installed; run with `uv run --extra bench` "
            "(the pinned version is in benchmarks/requirements-ci.in)"
        ) from None
    path = Path(plotly.__file__).parent / "validators" / "_validators.json"
    if not path.exists():  # pragma: no cover - depends on the plotly release
        raise SystemExit(
            f"plotly {plotly.__version__} has no {path.name}; see this script's docstring"
        )
    return json.loads(path.read_text(encoding="utf-8")), plotly.__version__


def attribute_paths(schema: dict[str, dict]) -> list[str]:
    """Leaf attributes only, minus the `*src` column-reference companions.

    A compound node is a namespace, not a knob, and `marker.colorsrc` is not a
    second styling decision beside `marker.color` — counting either would pad
    the denominator in XY's favour, which is the wrong direction to be wrong in.
    """
    skip = {"CompoundValidator", "CompoundArrayValidator", "SrcValidator"}
    return sorted(path for path, node in schema.items() if node["superclass"] not in skip)


def classify(path: str) -> tuple[str, str, str]:
    """-> (verdict, xy surface, reason). First matching rule wins."""
    root = path.split(".", 1)[0]
    if root not in META_ROOTS and root != "layout":
        equivalent = TRACE_EQUIVALENTS.get(root)
        if equivalent is None:
            return UNSUPPORTED, "", f"no such trace: XY does not implement {root!r}"
        if not equivalent:
            return UNSUPPORTED, "", f"{root!r} is explicitly out of v1"
    for rule in RULES:
        if fnmatch.fnmatch(path, rule.pattern):
            return rule.verdict, rule.surface, rule.note
    return UNSUPPORTED, "", "unclassified"


def build_report(schema: dict[str, dict], version: str) -> tuple[str, dict]:
    """Classify every attribute and render the report plus its summary counts."""
    paths = attribute_paths(schema)
    rows = [(path, *classify(path)) for path in paths]
    verdicts = Counter(verdict for _, verdict, _, _ in rows)
    reasons = Counter(reason for _, verdict, _, reason in rows if verdict == UNSUPPORTED)

    implemented = sorted(k for k, v in TRACE_EQUIVALENTS.items() if v)
    in_scope = [r for r in rows if r[0].split(".", 1)[0] in {*implemented, "layout"}]
    in_scope_verdicts = Counter(verdict for _, verdict, _, _ in in_scope)

    summary = {
        "plotly_version": version,
        "attributes": len(paths),
        "verdicts": dict(verdicts),
        "in_scope_attributes": len(in_scope),
        "in_scope_verdicts": dict(in_scope_verdicts),
        "unsupported_reasons": dict(reasons.most_common()),
        "implemented_trace_types": implemented,
    }

    def pct(n: int, d: int) -> str:
        return f"{100.0 * n / d:.1f}%" if d else "n/a"

    lines = [
        "# Plotly attribute coverage",
        "",
        "<!-- generated by scripts/plotly_schema_coverage.py --write; do not edit -->",
        "",
        f"Measured against **plotly {version}**, "
        f"`plotly/validators/_validators.json`, {len(paths):,} leaf attributes "
        "(compound namespaces and `*src` column-reference companions excluded).",
        "",
        "## Whole schema",
        "",
        "| verdict | attributes | share |",
        "|---|---|---|",
    ]
    for verdict in (SUPPORTED, MAPPED, UNSUPPORTED):
        count = verdicts.get(verdict, 0)
        lines.append(f"| {verdict} | {count:,} | {pct(count, len(paths))} |")
    lines += [
        "",
        "That denominator is dominated by trace types XY does not implement, so",
        "the whole-schema share is a poor headline number. The scoped one below",
        "is the number worth quoting, and it must be quoted *with* its scope.",
        "",
        "## Scoped to the trace types XY implements, plus `layout`",
        "",
        f"Trace types: {', '.join(f'`{name}`' for name in implemented)}. "
        f"{len(in_scope):,} attributes.",
        "",
        "| verdict | attributes | share |",
        "|---|---|---|",
    ]
    for verdict in (SUPPORTED, MAPPED, UNSUPPORTED):
        count = in_scope_verdicts.get(verdict, 0)
        lines.append(f"| {verdict} | {count:,} | {pct(count, len(in_scope))} |")
    lines += [
        "",
        "## Why attributes are unsupported",
        "",
        "Every unsupported attribute is accounted for: the table lists the "
        "fifteen largest reasons and folds the rest into one row, so the column "
        "sums to the unsupported total above rather than trailing off.",
        "",
        "| reason | attributes |",
        "|---|---|",
    ]
    top = reasons.most_common(15)
    for reason, count in top:
        lines.append(f"| {reason} | {count:,} |")
    remainder = sum(reasons.values()) - sum(count for _, count in top)
    if remainder:
        lines.append(
            f"| all other reasons ({len(reasons) - len(top)} more, "
            f"each smaller than the rows above) | {remainder:,} |"
        )
    lines.append(f"| **total unsupported** | **{sum(reasons.values()):,}** |")
    lines += [
        "",
        "`unclassified` is the honest residue: attributes no committed rule in",
        "`scripts/plotly_schema_coverage.py` claims. It is reported rather than",
        "folded into a friendlier bucket, and shrinking it is how this table",
        "improves.",
        "",
        "## Reproducing",
        "",
        "```bash",
        "uv run --extra bench python scripts/plotly_schema_coverage.py --check",
        "```",
        "",
        "`--check` fails if this file is stale. The rules it applies are in the",
        "`RULES` table of that script, one line per claim, so any row here can be",
        "traced to the claim that produced it.",
        "",
    ]
    return "\n".join(lines), summary


def main(argv: list[str] | None = None) -> int:
    """Print, write, or check the committed coverage report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate the committed report")
    parser.add_argument(
        "--check", action="store_true", help="fail if the committed report is stale"
    )
    parser.add_argument("--json", type=Path, help="also write the summary as JSON")
    args = parser.parse_args(argv)

    schema, version = load_schema()
    report, summary = build_report(schema, version)

    if args.json:
        args.json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if args.write:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(report, encoding="utf-8")
        print(f"wrote {REPORT.relative_to(ROOT)}")
        return 0
    if args.check:
        current = REPORT.read_text(encoding="utf-8") if REPORT.exists() else ""
        if current != report:
            print(
                f"{REPORT.relative_to(ROOT)} is stale; "
                "run scripts/plotly_schema_coverage.py --write",
                file=sys.stderr,
            )
            return 1
        print(f"{REPORT.relative_to(ROOT)} is current")
        return 0
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
