"""Engine tuning constants, shared across modules (figure, interaction, export).

Every threshold here is a *tier decision* from the design dossier — moving a
trace between direct draw, decimation, and aggregation — and each decision is
recorded in the shipped spec, never silent (§28).
"""

from __future__ import annotations

# Wire protocol version: the client refuses a mismatched spec loudly (§33).
PROTOCOL_VERSION = 2

# Line traces longer than this ship M4-decimated (Tier 1, §5); the canonical
# column stays kernel-side for re-decimation on zoom (§28: recompute for the
# visible x-range only).
DECIMATION_THRESHOLD = 10_000

# Scatter above this many points switches to Tier-2 density aggregation (§5):
# instead of shipping/drawing every point (fill-rate + the ~1 GB single-alloc
# cliff, §5 F3), the kernel bins the viewport into a density grid and the client
# colormaps it. Screen-bounded transport and VRAM regardless of point count.
SCATTER_DENSITY_THRESHOLD = 200_000

# Absolute direct-draw ceiling; above this, density is forced even if the user
# asked for per-point channels (they can't survive count-aggregation without the
# §5-F5 aggregation algebra — we warn and drop them, never silently mislead).
DIRECT_SOFT_CEILING = 2_000_000

# Default density grid resolution (cells). Screen-bounded (§5); the client
# requests a viewport-matched size on zoom via density_view.
DENSITY_GRID = (512, 384)

# Hysteresis on the drill boundary (§5 "tier transitions hysteresis-guarded"):
# once drilled to points, stay until the visible count clearly exceeds the
# budget again, so a view hovering at the threshold doesn't thrash modes.
DRILL_EXIT_FACTOR = 1.15

# Aggregation grids aim for this many points per cell when the visible count
# is barely over the direct budget — one-point-per-pixel grids look like
# static and re-ship large; a few points per cell keeps drill-out continuous.
DENSITY_TARGET_POINTS_PER_CELL = 16.0

# CVD-safe default categorical palette (§20/§36 default theme).
DEFAULT_PALETTE = [
    "#4c78a8",
    "#f58518",
    "#54a24b",
    "#e45756",
    "#72b7b2",
    "#eeca3b",
    "#b279a2",
    "#ff9da6",
    "#9d755d",
    "#bab0ac",
]
