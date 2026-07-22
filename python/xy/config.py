"""Engine tuning constants, shared across modules (figure, interaction, export).

Every threshold here is a *tier decision* from the design dossier — moving a
trace between direct draw, decimation, and aggregation — and each decision is
recorded in the shipped spec, never silent (§28).
"""

from __future__ import annotations

# Wire protocol version: the client refuses a mismatched spec loudly (§33).
# v5: streaming append ships split-layout buffers, once per tick.
# v6: append reuse — split columns carry `cid` identities, append messages
# may ship cid-only entries the client resolves from bytes it already holds
# (recovery via the `refresh` request), and the widget's synced traits become
# debounced reopen state while the per-tick push is a custom message again.
PROTOCOL_VERSION = 6

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

# Tile pyramid (§5 Tier 3): built lazily per density trace at/above this size;
# base level is PYRAMID_BASE_DIM² u32 counts (~4·dim² bytes + 1/3 overhead).
PYRAMID_MIN_POINTS = 2_000_000
PYRAMID_BASE_DIM = 2048
