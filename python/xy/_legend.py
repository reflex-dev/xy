"""Resolved legend entries shared by payload policy and static exporters."""

from __future__ import annotations

from collections.abc import Sequence

from .config import DEFAULT_PALETTE


def legend_items(traces: list[dict], palette: Sequence[str] = DEFAULT_PALETTE) -> list[dict]:
    """Legend rows for a trace list — shared by the SVG and raster exporters.

    A categorical `color=` channel is ONE trace carrying N categories, so the
    old `[t for t in traces if t.get("name")]` drew a single row bearing the
    trace's name and the trace's constant color: a legend that actively
    misdescribed the picture beside it. Expand those into one row per category,
    exactly as `ChartView._buildLegend` does for the live client.

    Args:
        traces: Emitted trace specifications.
        palette: Fallback categorical palette when a channel has none.

    Returns:
        Static legend rows, with categorical channels expanded into entries.
    """
    items: list[dict] = []
    for trace in traces:
        style = dict(trace.get("style") or {})
        use_trace_size = bool(style.pop("_legend_trace_size", False))
        size = trace.get("size") or {}
        if trace.get("kind") == "scatter" and use_trace_size and size.get("mode") == "constant":
            style["size"] = float(size.get("size", 8.0))
        color = trace.get("color") or {}
        if color.get("mode") == "categorical":
            categories = color.get("categories") or []
            entry_palette = list(color.get("palette") or palette) or list(palette)
            for index, category in enumerate(categories):
                item_style = dict(style)
                item_style["color"] = entry_palette[index % len(entry_palette)]
                items.append(
                    {"name": str(category), "kind": trace.get("kind"), "style": item_style}
                )
        elif trace.get("name"):
            item = dict(trace)
            item["style"] = style
            items.append(item)
    return items


def automatic_legend_visible(traces: list[dict]) -> bool:
    """Keep encoding legends and legends with more than one ordinary series.

    Auto suppression only applies to simple named series. Per-row color, size,
    stroke, and style channels can carry meaning beyond the series name, so
    their legends retain the explicit-True behavior.

    Args:
        traces: Emitted trace specifications, after channel resolution.

    Returns:
        Whether the built-in main legend should remain enabled.
    """
    for trace in traces:
        if trace.get("kind") not in {
            "line",
            "scatter",
            "area",
            "bar",
            "column",
            "histogram",
            "hist",
            "step",
            "stairs",
            "segments",
            "errorbar",
            "error_band",
        }:
            return True
        if trace.get("channels"):
            return True
        for key in ("color", "size", "stroke"):
            mode = (trace.get(key) or {}).get("mode")
            if mode not in (None, "constant"):
                return True
    return len(legend_items(traces)) > 1
