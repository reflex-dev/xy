"""The `Trace` value object — one built chart series, canonical f64
columns plus tier/drill bookkeeping. Split out of `_figure.py` so both the
builders (`figure`) and the wire-spec emitters (`_payload`) can share it
without a load-time cycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .channels import ColorChannel, SizeChannel, StyleChannel
from .columns import Column
from .config import DIRECT_SOFT_CEILING, SCATTER_DENSITY_THRESHOLD


@dataclass
class Trace:
    id: int
    kind: str  # public and internal mark kind
    x: Column
    y: Column
    x_axis: str = "x"
    y_axis: str = "y"
    name: Optional[str] = None
    style: dict[str, Any] = field(default_factory=dict)
    # Area-style marks keep an explicit baseline column; rectangle-like marks
    # use x0/x1/y0/y1 below.
    base: Optional[Column] = None
    # Grid-like marks (heatmap/image) ship one scalar grid plus metadata instead
    # of four rectangle columns per cell.
    grid: Optional[Column] = None
    rgba_grid: Optional[tuple[Column, Column, Column, Column]] = None
    grid_shape: Optional[tuple[int, int]] = None  # (rows, columns)
    count: Optional[int] = None
    # Rect-like marks ship four geometry columns. `x`/`y` remain conventional
    # center/value columns for bars; independent-segment traces may alias x0/y0
    # because their endpoint columns drive payloads and autorange directly.
    x0: Optional[Column] = None
    x1: Optional[Column] = None
    y0: Optional[Column] = None
    y1: Optional[Column] = None
    color_ch: Optional[ColorChannel] = None  # scatter color encoding
    # Independent per-mark outline paint.  ``None`` means the mark family has
    # no outline; a constant ``None`` color inside the channel means
    # edgecolors="face" and is resolved against color_ch by the renderers.
    stroke_ch: Optional[ColorChannel] = None
    size_ch: Optional[SizeChannel] = None  # scatter size encoding
    # Declarative data-transition metadata. Keys are two uint32 words per
    # canonical row (a deterministic 64-bit digest), kept out of the f64
    # column store because they are identity rather than numeric geometry.
    animation: Optional[dict[str, Any]] = None
    transition_keys: Optional[Any] = None
    # Direct, final-unit instance attributes (alpha override, opacity, widths,
    # symbols, corner radii).  Constants stay in ``style`` and cost no buffer.
    style_channels: dict[str, StyleChannel] = field(default_factory=dict)
    # Tri-state density override: None = auto (threshold), True/False = forced.
    # (A bool here silently ignored density=False — staff-review finding.)
    force_density: Optional[bool] = None
    # Shipped-row → canonical-row mapping, set by build_payload when the shipped
    # copy drops NaN rows (§19), and by the drill-in view path when a Tier-2
    # trace ships its visible subset. The client's GPU pick and selection masks
    # speak in *shipped* indices; canonical readouts must translate through this
    # or hover/selection silently report the wrong rows.
    shipped_sel: Optional[Any] = None
    # Tier-2 drill state (§5: tier follows the *visible* count): True while the
    # current view ships real points instead of the density grid. Kernel-side
    # only — the per-view decision itself rides each update (§28).
    drill_mode: bool = False
    # Monotonic version of shipped_sel. Every drill update bumps it and ships
    # it; pick/selection echo it back so a reply computed against a *different*
    # subset is dropped instead of translating indices in the wrong space
    # (§16/§17: exact readout beats stale availability).
    drill_seq: int = 0
    # Recent shipped subsets, {drill_seq: sel}, bounded to DRILL_HISTORY_KEEP
    # (LOD doc T13): the client may pick against a retired cached point window
    # whose seq is no longer current — translating through the remembered
    # subset keeps that hover exact instead of dead. Cleared on data changes
    # (an old subset's indices would then name different rows — §16).
    drill_history: dict[int, Any] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    # Count-pyramid cache (§5 Tier 3), managed by `interaction.py`: None =
    # never tried, 0 = tried and not applicable, otherwise the native handle.
    # The finalizer frees the native side when the trace is collected.
    # `_pyr_colored` records whether the handle carries mean-color planes
    # (LOD doc §2) — compose must ask for them, and the memory report counts them.
    _pyr_handle: Optional[int] = field(default=None, init=False, repr=False, compare=False)
    _pyr_colored: bool = field(default=False, init=False, repr=False, compare=False)
    _pyr_finalizer: Optional[Any] = field(default=None, init=False, repr=False, compare=False)
    _pyr_base_dim: int = field(default=0, init=False, repr=False, compare=False)
    # Optional Tier-3 spatial index (xy._spatial.SpatialIndex) for O(window)
    # exact deep-zoom density; attached out-of-band, duck-typed in interaction.
    _spatial_index: Any = field(default=None, init=False, repr=False, compare=False)

    @property
    def n_points(self) -> int:
        if self.count is not None:
            return self.count
        return len(self.x)

    def per_item_channel_names(self) -> tuple[str, ...]:
        """Names of channels whose values vary independently per rendered item."""
        names: list[str] = []
        if self.color_ch is not None and self.color_ch.mode != "constant":
            names.append("color")
        if self.stroke_ch is not None and self.stroke_ch.mode not in ("constant", "match_fill"):
            names.append("stroke")
        if self.size_ch is not None and self.size_ch.mode != "constant":
            names.append("size")
        names.extend(self.style_channels)
        return tuple(names)

    def has_per_item_channels(self) -> bool:
        """Whether this trace must preserve independently styled items."""
        return bool(self.per_item_channel_names())

    def use_density(self) -> bool:
        """Whether this scatter renders as a Tier-2 density grid (§5)."""
        if self.kind != "scatter":
            return False
        if self.force_density is not None:
            return self.force_density
        # Per-point channels keep direct draw until the hard ceiling; plain
        # scatter aggregates earlier (its whole win is not drawing 10M dots).
        threshold = (
            DIRECT_SOFT_CEILING if self.has_per_item_channels() else SCATTER_DENSITY_THRESHOLD
        )
        return self.n_points > threshold
