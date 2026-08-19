"""Funnel stage arithmetic and segment geometry.

Pure build-time layout, the way `_sankey.compute_layout` owns the Sankey
placement: validation, conversion/drop-off arithmetic, quad construction and
the label-placement ladder all happen here, and the renderers only ever see
`funnel` quads plus semantic tooltip rows. Everything is deterministic in the
declared stage order — a funnel is a categorical business process, and this
module never reorders it.

Coordinates are orientation-neutral: `pos` runs along the stage axis (one unit
per stage, stage 0 first) and `cross` runs across it, centered on zero. The
mark maps pos→y/cross→x for vertical funnels and pos→x/cross→y for horizontal
ones; `funnel_chart` reverses the vertical stage axis so stage 0 reads from
the top.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Optional

from . import _fontmetrics

ORIENTATIONS = ("vertical", "horizontal")
GEOMETRIES = ("area", "bar")
NECKS = ("rect", "taper")

# Mode-resolved segment gaps (fraction of the unit stage pitch). An area
# funnel reads as one tapering silhouette, so its segments touch; bars need
# the same separation a bar chart's 0.8 width leaves.
DEFAULT_GAP = {"area": 0.0, "bar": 0.2}


@dataclass(frozen=True)
class FunnelStage:
    """One stage with its conversion arithmetic resolved.

    `share` is the overall conversion (value / first value), `conversion` the
    previous-stage conversion (value / prior). Both are None where the
    denominator is zero or absent — the first stage has no prior, and a zero
    denominator has no meaningful ratio — so formatting shows an em dash
    instead of an invented number.
    """

    index: int
    name: str
    value: float
    share: Optional[float]
    prior: Optional[float]
    conversion: Optional[float]
    dropoff: Optional[float]


@dataclass(frozen=True)
class FunnelQuad:
    """One drawn segment: a symmetric trapezoid in pos/cross space.

    `pos0` is the leading edge (toward stage 0), `pos1` the trailing edge;
    `lo0/hi0` are the cross-axis edges at pos0 and `lo1/hi1` at pos1. A bar
    segment is the degenerate trapezoid with equal ends.
    """

    stage: int
    pos0: float
    pos1: float
    lo0: float
    hi0: float
    lo1: float
    hi1: float


@dataclass(frozen=True)
class FunnelLayout:
    stages: list[FunnelStage]
    quads: list[FunnelQuad]
    orientation: str
    geometry: str
    gap: float
    max_value: float
    # The drawn half-width floor in value units (min_width × max_value / 2);
    # tooltip/event values are never clamped, only drawn geometry.
    floor_half: float


@dataclass(frozen=True)
class FunnelLabelSpec:
    """One resolved label: text, position, and the placement decision."""

    stage: int
    kind: str  # "value" | "dropoff"
    text: str
    pos: float
    cross: float
    anchor: str  # "start" | "middle" | "end"
    placement: str  # "inside" | "outside" | "hidden"


def _validated_values(names: Sequence[str], values: Sequence[float]) -> list[float]:
    if len(names) != len(values):
        raise ValueError(
            f"funnel needs one value per stage; got {len(names)} stages and {len(values)} values"
        )
    if not names:
        raise ValueError("funnel needs at least one stage")
    seen: dict[str, int] = {}
    for index, name in enumerate(names):
        if name in seen:
            raise ValueError(
                f"funnel stage names must be unique; {name!r} appears at "
                f"positions {seen[name]} and {index}"
            )
        seen[name] = index
    out: list[float] = []
    for name, value in zip(names, values, strict=True):
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"funnel stage {name!r} has a non-numeric value {value!r}") from None
        if math.isnan(v):
            raise ValueError(
                f"funnel stage {name!r} has a missing value; drop the stage "
                "or supply a number (zero is allowed)"
            )
        if math.isinf(v):
            raise ValueError(f"funnel stage {name!r} has a non-finite value")
        if v < 0.0:
            raise ValueError(
                f"funnel stage {name!r} has a negative value ({v:g}); stage "
                "values are counts or amounts and must be >= 0"
            )
        out.append(v)
    return out


def _ratio(numerator: float, denominator: float) -> Optional[float]:
    """A conversion ratio, or None where one is not defined.

    Zero denominators have no ratio, and neither does an overflow: a wide
    enough dynamic range (1e-300 -> 1e10) makes a bare division inf, which is
    not JSON, not a wire value, and not a number any reader wants printed.
    Both are the same answer to the same question — "no meaningful ratio
    here" — and both render as the em dash.
    """
    if denominator <= 0.0:
        return None
    value = numerator / denominator
    return value if math.isfinite(value) else None


def compute_stages(names: Sequence[str], values: Sequence[float]) -> list[FunnelStage]:
    """Validate stage values and resolve conversion arithmetic.

    Increasing values are allowed (re-entry and net-growth funnels are real)
    and produce conversion > 1 with a negative drop-off; negative and missing
    values are refused by stage name. A ratio with a zero denominator — or one
    that overflows to infinity — is None, never inf.
    """
    vals = _validated_values(names, values)
    first = vals[0]
    stages: list[FunnelStage] = []
    prior: Optional[float] = None
    for index, (name, value) in enumerate(zip(names, vals, strict=True)):
        share = _ratio(value, first)
        if index == 0:
            conversion: Optional[float] = None
            dropoff: Optional[float] = None
        elif prior is not None:
            conversion = _ratio(value, prior)
            dropoff = None if conversion is None else 1.0 - conversion
        else:
            conversion = None
            dropoff = None
        stages.append(
            FunnelStage(
                index=index,
                name=name,
                value=value,
                share=share,
                prior=prior,
                conversion=conversion,
                dropoff=dropoff,
            )
        )
        prior = value
    return stages


def _validated_layout_options(
    *,
    orientation: str,
    geometry: str,
    gap: Optional[float],
    neck: str,
    min_width: float,
) -> tuple[float, float]:
    """Validate data-independent layout options and return normalized values.

    Kept separate from :func:`compute_layout` so structural probes can run
    the exact same configuration gate without fabricating a stage merely to
    reach it. Stage/value coupling remains a real-data validation below.
    """
    if orientation not in ORIENTATIONS:
        raise ValueError(f"funnel orientation must be one of {ORIENTATIONS}, got {orientation!r}")
    if geometry not in GEOMETRIES:
        raise ValueError(f"funnel geometry must be one of {GEOMETRIES}, got {geometry!r}")
    if neck not in NECKS:
        raise ValueError(f"funnel neck must be one of {NECKS}, got {neck!r}")
    if neck != "rect" and geometry != "area":
        raise ValueError('funnel neck applies to geometry="area" only; bar segments have no taper')
    if gap is None:
        gap_value = DEFAULT_GAP[geometry]
    else:
        gap_value = float(gap)
        if not 0.0 <= gap_value < 1.0:
            raise ValueError(f"funnel gap must be in [0, 1), got {gap!r}")
    min_width_value = float(min_width)
    if not 0.0 <= min_width_value <= 1.0:
        raise ValueError(f"funnel min_width must be in [0, 1], got {min_width!r}")
    return gap_value, min_width_value


def compute_layout(
    names: Sequence[str],
    values: Sequence[float],
    *,
    orientation: str = "vertical",
    geometry: str = "area",
    gap: Optional[float] = None,
    neck: str = "rect",
    min_width: float = 0.0,
) -> FunnelLayout:
    """Build the drawn quads for a funnel in declared stage order.

    - ``geometry="area"``: equal-length segments whose cross width tapers from
      this stage's value to the next stage's, so drop-off is visible as slope.
      The painted area is therefore NOT proportional to the stage value — the
      docs say so — and ``geometry="bar"`` is the faithful-width alternative.
    - ``geometry="bar"``: centered constant-width segments (widths carry the
      values exactly).
    - ``neck`` decides the last area segment's far edge: ``"rect"`` holds the
      stage's own width, ``"taper"`` runs it to a point.
    - ``min_width`` clamps drawn cross widths to a fraction of the widest
      stage so zero/tiny stages stay visible and hoverable; values in events,
      tooltips and labels are never clamped.
    """
    gap_value, min_width_value = _validated_layout_options(
        orientation=orientation,
        geometry=geometry,
        gap=gap,
        neck=neck,
        min_width=min_width,
    )

    stages = compute_stages(names, values)
    max_value = max(stage.value for stage in stages)
    floor_half = min_width_value * max_value / 2.0

    def half(value: float) -> float:
        return max(value / 2.0, floor_half)

    quads: list[FunnelQuad] = []
    n = len(stages)
    for stage in stages:
        pos0 = stage.index - 0.5 + gap_value / 2.0
        pos1 = stage.index + 0.5 - gap_value / 2.0
        lead = half(stage.value)
        if geometry == "bar":
            trail = lead
        elif stage.index + 1 < n:
            trail = half(stages[stage.index + 1].value)
        elif neck == "taper":
            # The spout: the funnel's last segment runs to a point. The floor
            # deliberately does not apply — a point is the documented shape,
            # not an accidentally invisible stage.
            trail = 0.0
        else:
            trail = lead
        quads.append(
            FunnelQuad(
                stage=stage.index,
                pos0=pos0,
                pos1=pos1,
                lo0=-lead,
                hi0=lead,
                lo1=-trail,
                hi1=trail,
            )
        )
    return FunnelLayout(
        stages=stages,
        quads=quads,
        orientation=orientation,
        geometry=geometry,
        gap=gap_value,
        max_value=max_value,
        floor_half=floor_half,
    )


def format_ratio(ratio: Optional[float], percent_format: str) -> str:
    """A conversion/share ratio for display; an em dash where undefined."""
    if ratio is None:
        return "—"
    return percent_format.format(ratio)


def format_value(value: float, value_format: str) -> str:
    return value_format.format(value)


def _fits(px: float, budget: float) -> bool:
    return px <= budget


def decide_labels(
    layout: FunnelLayout,
    *,
    show_values: bool,
    show_conversion: bool,
    show_dropoff: bool,
    value_format: str,
    percent_format: str,
    font_size: float,
    plot_px: tuple[float, float],
) -> list[FunnelLabelSpec]:
    """Resolve label texts and placements with the documented collision ladder.

    For each stage the value label (value, plus overall conversion when
    ``show_conversion``) tries, in order:

    1. **inside** — centered in the segment, when the text fits the box the
       segment actually offers: cross width × stage pitch for a vertical
       funnel, stage pitch × cross height for a horizontal one (text always
       runs horizontally, so the axis it is measured against transposes with
       the orientation);
    2. **outside** — beside a vertical segment on the positive cross side, or
       above a horizontal one, when the segment's box fails but the stage
       pitch can still hold the text without hitting the neighbours;
    3. **hidden** — when even the outside slot cannot hold the text (the
       tooltip and events still carry every number).

    Drop-off labels (``show_dropoff``) sit outside at the boundary between a
    stage and its predecessor, formatted as the signed change
    (``-38%`` for a drop, ``+12%`` for growth), and inherit the same
    outside-or-hidden rule. Placement is estimated against the figure's
    configured pixel size at build time; a responsive chart keeps the
    build-time decision.
    """
    plot_w, plot_h = plot_px
    n = len(layout.stages)
    # Cross span the mark occupies: the widest drawn edge on each side, plus
    # the small margin funnel_chart adds. Conservative: labels care about
    # scale, not exact margins.
    cross_full = 2.0 * max((max(quad.hi0, quad.hi1) for quad in layout.quads), default=0.5)
    if cross_full <= 0.0:
        # Every stage is zero-valued with no floor: nothing has drawable
        # width, so nothing fits "inside" and every label falls outside.
        cross_full = 1.0
    horizontal = layout.orientation == "horizontal"
    if horizontal:
        cross_px_per_unit = plot_h / (cross_full * 1.1)
        pitch_px = plot_w / max(n, 1)
    else:
        cross_px_per_unit = plot_w / (cross_full * 1.1)
        pitch_px = plot_h / max(n, 1)
    line_px = font_size * 1.4

    labels: list[FunnelLabelSpec] = []
    for stage, quad in zip(layout.stages, layout.quads, strict=True):
        mid_pos = (quad.pos0 + quad.pos1) / 2.0
        mid_half = (quad.hi0 + quad.hi1) / 2.0
        seg_pitch_px = pitch_px * (quad.pos1 - quad.pos0)
        seg_cross_px = mid_half * 2.0 * cross_px_per_unit
        if show_values:
            text = format_value(stage.value, value_format)
            if show_conversion:
                text += f"  {format_ratio(stage.share, percent_format)}"
            width_px = _fontmetrics.advance(text, font_size)
            # The box a horizontally-running text line must fit: along the
            # text, the segment's HORIZONTAL extent (cross width when the
            # funnel is vertical, stage pitch when it is horizontal); across
            # the text, the segment's vertical extent.
            along_px = seg_pitch_px if horizontal else seg_cross_px
            across_px = seg_cross_px if horizontal else seg_pitch_px
            # An outside label still occupies the stage's slot along the
            # pitch axis for a horizontal funnel (it sits above its own
            # segment), so a text wider than the pitch collides with the
            # neighbours' labels and hides instead. Vertical outside labels
            # extend into the margin and only need their line height.
            outside_ok = _fits(width_px, pitch_px) if horizontal else _fits(line_px, pitch_px)
            if _fits(width_px, along_px * 0.92) and _fits(line_px, across_px):
                placement, cross, anchor = "inside", 0.0, "middle"
            elif outside_ok:
                # A vertical outside label runs into the side margin from the
                # segment's edge; a horizontal one sits ABOVE its own stage,
                # so it centers there — a start anchor at the stage midpoint
                # hung half the text over the neighbour and clipped the last
                # stage at the plot edge.
                anchor = "middle" if horizontal else "start"
                placement, cross = "outside", mid_half
            else:
                placement, cross, anchor = "hidden", 0.0, "middle"
            labels.append(
                FunnelLabelSpec(
                    stage=stage.index,
                    kind="value",
                    text=text,
                    pos=mid_pos,
                    cross=cross,
                    anchor=anchor,
                    placement=placement,
                )
            )
        if show_dropoff and stage.index > 0:
            change = None if stage.conversion is None else stage.conversion - 1.0
            if change is None:
                text = "—"
            else:
                text = percent_format.format(change)
                if change > 0.0 and not text.startswith(("+", "-")):
                    text = "+" + text
            boundary = stage.index - 0.5
            prev_quad = layout.quads[stage.index - 1]
            edge = max(prev_quad.hi1, quad.hi0)
            drop_px = _fontmetrics.advance(text, font_size)
            # Same transposition as the value labels: a horizontal funnel's
            # boundary labels sit side by side along the pitch axis, so their
            # WIDTH is what collides; a vertical funnel stacks them and only
            # the line height competes for the pitch.
            placement = (
                "outside"
                if (_fits(drop_px, pitch_px) if horizontal else _fits(line_px, pitch_px))
                else "hidden"
            )
            labels.append(
                FunnelLabelSpec(
                    stage=stage.index,
                    kind="dropoff",
                    text=text,
                    pos=boundary,
                    cross=edge,
                    anchor="start",
                    placement=placement,
                )
            )
    return labels
