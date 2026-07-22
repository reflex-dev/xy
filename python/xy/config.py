"""Engine tuning constants, shared across modules (figure, interaction, export).

Every threshold here is a *tier decision* from the design dossier — moving a
trace between direct draw, decimation, and aggregation — and each decision is
recorded in the shipped spec, never silent (§28).
"""

from __future__ import annotations

import warnings

# Wire protocol version: the client refuses a mismatched spec loudly (§33).
# v5: streaming append ships split-layout buffers and, on the widget host,
# rides the spec/buffers trait update (`spec.append.seq`) with no custom send.
# v6: symlog axis scale (`scale: "symlog"` + `constant`) and scale-coordinate
# density grids — an older cached client would render both silently wrong.
PROTOCOL_VERSION = 6

# Line traces longer than this ship M4-decimated (Tier 1, §5); the canonical
# column stays kernel-side for re-decimation on zoom (§28: recompute for the
# visible x-range only).
DECIMATION_THRESHOLD = 10_000

# Scatter above this many points switches to Tier-2 density aggregation (§5):
# instead of shipping/drawing every point (fill-rate + the ~1 GB single-alloc
# cliff, §5 F3), the kernel bins the viewport into a density grid the client
# draws with the trace's own colors — count drives only the alpha (LOD doc
# §2). Screen-bounded transport and VRAM regardless of point count.
SCATTER_DENSITY_THRESHOLD = 200_000

# Absolute direct-draw ceiling; above this, density is forced even if the user
# asked for per-point channels. The color channel survives as the surface's
# per-cell mean point color (LOD doc §2); the rest (size, stroke, styles) have
# no honest per-cell aggregate yet (§5 F5) — we warn and drop them, never
# silently mislead.
DIRECT_SOFT_CEILING = 2_000_000

# Stable-key matching retains a browser-side identity table for only bounded
# direct traces. Larger/density traces fall back explicitly to index/snap
# rather than allocating an unbounded JS Map alongside canonical data.
MAX_ANIMATION_MATCH_ROWS = 200_000

# Default density grid resolution (cells). Screen-bounded (§5); the client
# requests a viewport-matched size on zoom via density_view.
DENSITY_GRID = (512, 384)

# Absolute cap for any browser-supplied screen dimension. Frontends normally
# send plot CSS pixels, but widget/comm messages are still untrusted input; this
# prevents a bad `px` from turning into huge decimation buckets or density grids.
MAX_SCREEN_DIM = 4096

# Contour extraction is native and output-bounded, but its work still scales
# with grid cells × levels. Keep one request from allocating an unbounded
# segment buffer before the browser can apply any screen-size limit.
MAX_CONTOUR_WORK = 4_000_000

# Hysteresis on the drill boundary (§5 "tier transitions hysteresis-guarded"):
# once drilled to points, stay until the visible count clearly exceeds the
# budget again, so a view hovering at the threshold doesn't thrash modes.
DRILL_EXIT_FACTOR = 1.15

# Aggregation grids aim for this many points per cell when the visible count
# is barely over the direct budget — one-point-per-pixel grids look like
# static and re-ship large; a few points per cell keeps drill-out continuous.
DENSITY_TARGET_POINTS_PER_CELL = 16.0

# Hybrid density overlay (§5): when scatter is aggregated, ship a small,
# deterministic sample of real points over the density texture. This keeps
# zoomed-out views from becoming pure heatmaps while staying payload-bounded.
DENSITY_SAMPLE_TARGET = 8_192
DENSITY_SAMPLE_SEED = 0

# CVD-safe default categorical palette (§20/§36 default theme). Eight slots in
# a fixed order; charts render on unknown host surfaces, so every step sits in
# the OKLCH lightness band both light and dark modes share (L 0.48–0.67) and is
# validated against both reference surfaces (#fcfcfb / #1a1a19) with
# .claude/skills/xy-dataviz/scripts/validate_palette.py: chroma ≥ 0.10, worst
# adjacent-pair CVD ΔE 8.5 (Machado–Oliveira–Fernandes protan/deutan, ≥8
# target), worst adjacent normal-vision ΔE 19.1 (≥15 floor), all slots ≥3:1 on
# both surfaces. The ORDER is the CVD-safety mechanism — adjacency drives the
# ΔE gate — so never re-order or extend without re-running the validator.
# (Replaced Tableau10, whose adjacent red/green collapsed to ΔE 1.2 under
# deuteranopia and whose slots 1/5/7/9/10 sat below the chroma floor.)
DEFAULT_PALETTE = [
    "#3987e5",  # blue
    "#008300",  # green
    "#d55181",  # magenta
    "#c48300",  # amber
    "#199e70",  # aqua
    "#d95926",  # orange
    "#9085e9",  # violet
    "#e66767",  # red
]

_PALETTE_WRAP_MESSAGE = (
    f"more than {len(DEFAULT_PALETTE)} series use default colors; the default "
    f"palette repeats every {len(DEFAULT_PALETTE)} (series 9 wears series 1's "
    "color). Pass explicit color= per series, or group series, to keep "
    "identities distinct."
)


def default_palette_color(index: int, *, stacklevel: int = 3) -> str:
    """Default color for the `index`-th series (0-based): the palette, cycled.

    The palette is deliberately eight slots — the adjacency order above is the
    CVD-safety mechanism, so it cannot grow a ninth hue without re-clearing the
    validator — which means assignment wraps modulo eight. The wrap is allowed
    but never silent (§28): the first wrapped assignment warns.
    """
    if index >= len(DEFAULT_PALETTE):
        warnings.warn(_PALETTE_WRAP_MESSAGE, RuntimeWarning, stacklevel=stacklevel)
    return DEFAULT_PALETTE[index % len(DEFAULT_PALETTE)]


# Tile pyramid (§5 Tier 3): built lazily per density trace at/above this size;
# base level is PYRAMID_BASE_DIM² u32 counts (~4·dim² bytes + 1/3 overhead).
PYRAMID_MIN_POINTS = 2_000_000
PYRAMID_BASE_DIM = 2048
