"""An inventory of what XY can be styled with, and where each thing reaches.

One entry per CSS-addressable DOM slot and one per mark style property, each
carrying its support level in the WebGL client, the SVG writer, and the native
rasterizer. The styling surface is spread across `styles.py`, `dom.py`, the
three renderers, and the export paths, so answering "can I change this, and
will it survive `to_png()`" otherwise means reading all of them.

Two rules keep it accurate, both enforced by `tests/test_capability_registry.py`:

1. **It cannot drift.** The registry must cover exactly `dom.CHART_DOM_SLOTS`
   and exactly the property set `styles._supported_mark_style_properties`
   compiles — no more, no fewer. Adding a property without a registry entry
   fails the suite, and so does keeping an entry for a property that was
   removed.
2. **It does not restate what code already knows.** Which mark kinds accept a
   property is *derived* from `styles.py` at import, never typed out here, so
   the two cannot disagree.

Support levels are deliberately coarse: `full` means the renderer draws the
property as specified, `partial` means it draws something the notes have to
qualify, and `none` means it does not draw it at all. `none` is not a bug
report — several are deliberate, and the `notes` field says which.

Keep `id` values stable: they are the join key for the generated table.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .. import styles
from .._svg import STATIC_STYLED_SLOTS
from ..dom import CHART_DOM_SLOTS

#: The three mark renderers. Native PDF is intentionally absent: it is produced
#: from the SVG writer's output (`_pdf.svg_to_pdf`), so it inherits the `svg`
#: column exactly and a fourth column would imply an independent implementation
#: that does not exist.
RENDERERS: tuple[str, ...] = ("webgl", "svg", "native")

#: Where chrome slots can be styled. `browser` covers standalone HTML, the
#: notebook iframe, the widget, the Reflex adapter, and Chromium capture — all
#: of them render the same document with the same client.
SURFACES: tuple[str, ...] = ("browser", "native_raster", "native_vector")

SUPPORT_LEVELS: frozenset[str] = frozenset({"full", "partial", "none"})
STATUSES: frozenset[str] = frozenset({"shipped", "partial", "planned"})
VOCABULARIES: frozenset[str] = frozenset({"css", "svg", "xy"})

#: Interaction/view states that gate live-only chrome. A slot tagged with one
#: of these exists in the document only while its state is active — a tooltip
#: under hover, the modebar under a pointer, a reduction badge under the view
#: that triggered it, an axis gesture band only while its axis is navigable —
#: so a clean static export does not *contain* it. Styling such a slot is
#: therefore not "dropped" by a clean static export: there is nothing in the
#: file to style. Counting those slots against static parity overstated the
#: gap; tagging them records the distinction instead of leaving it silent
#: (§28).
EXPORT_STATES: tuple[str, ...] = (
    "hover",
    "selection",
    "crosshair",
    "modebar",
    "view",
    "navigation",
)

#: Every slot is either present in a clean static export ("static") or gated
#: by exactly one export state.
APPLICABILITIES: frozenset[str] = frozenset({"static", *EXPORT_STATES})


@dataclass(frozen=True)
class MarkStyleProperty:
    """One property accepted by a mark's `style=` mapping."""

    id: str
    vocabulary: str
    compiles_to: str
    support: dict[str, str]
    status: str
    notes: str

    @property
    def kinds(self) -> tuple[str, ...]:
        """Mark kinds that accept this property, read from `styles.py`."""
        return tuple(
            kind
            for kind in styles._MARK_KINDS
            if self.id in styles._supported_mark_style_properties(kind)
        )


@dataclass(frozen=True)
class SlotCapability:
    """One stable DOM slot and how far its styling travels."""

    id: str
    support: dict[str, str]
    notes: str
    channel: str = ""
    applicability: str = "static"


@dataclass(frozen=True)
class RendererDivergence:
    """A default the three renderers do not agree on.

    Typed like every other registry entry rather than left as a bare dict: a
    mistyped key in a dict fails silently at render time instead of raising.
    """

    id: str
    what: str
    webgl: str
    svg: str
    native: str
    visible_when: str
    tracked_by: str


@dataclass(frozen=True)
class ExtensionPoint:
    """A way to add behavior XY does not ship, without forking it."""

    id: str
    status: str
    entry_point: str
    notes: str
    limits: tuple[str, ...] = field(default_factory=tuple)


MARK_STYLE_PROPERTIES: tuple[MarkStyleProperty, ...] = (
    MarkStyleProperty(
        id="opacity",
        vocabulary="css",
        compiles_to="opacity",
        support={"webgl": "full", "svg": "full", "native": "full"},
        status="shipped",
        notes="Multiplies the mark's own alpha in every renderer.",
    ),
    MarkStyleProperty(
        id="fill",
        vocabulary="svg",
        compiles_to="color / fill",
        support={"webgl": "full", "svg": "full", "native": "full"},
        status="shipped",
        notes=(
            "A plain color compiles to the mark's paint; a `linear-gradient(...)` "
            "compiles to a gradient and is accepted only by area and rect kinds, "
            "which are the ones with a gradient program."
        ),
    ),
    MarkStyleProperty(
        id="fill-opacity",
        vocabulary="svg",
        compiles_to="fill_opacity",
        support={"webgl": "full", "svg": "full", "native": "full"},
        status="shipped",
        notes="Independent of `opacity`; the two multiply.",
    ),
    MarkStyleProperty(
        id="stroke",
        vocabulary="svg",
        compiles_to="color / line_color / stroke",
        support={"webgl": "full", "svg": "full", "native": "full"},
        status="shipped",
        notes="The paint for line-like geometry, and the border for filled marks.",
    ),
    MarkStyleProperty(
        id="stroke-opacity",
        vocabulary="svg",
        compiles_to="stroke_opacity",
        support={"webgl": "full", "svg": "full", "native": "full"},
        status="shipped",
        notes="",
    ),
    MarkStyleProperty(
        id="stroke-width",
        vocabulary="svg",
        compiles_to="width / line_width / stroke_width",
        support={"webgl": "full", "svg": "full", "native": "full"},
        status="shipped",
        notes="CSS px; a bare number is px, matching the chrome style convention.",
    ),
    MarkStyleProperty(
        id="stroke-dasharray",
        vocabulary="svg",
        compiles_to="dash",
        support={"webgl": "full", "svg": "full", "native": "full"},
        status="shipped",
        notes=(
            "2-8 positive px lengths, or `none`. The WebGL client tracks arc "
            "length on the CPU so dashes stay continuous across segments and "
            "constant on screen through zoom."
        ),
    ),
    MarkStyleProperty(
        id="stroke-linecap",
        vocabulary="svg",
        compiles_to="linecap",
        support={"webgl": "full", "svg": "full", "native": "full"},
        status="shipped",
        notes=(
            "Line family only — a cap is open-path geometry. XY's default is "
            "`round`, not CSS's `butt`, because the native rasterizer has always "
            "drawn round and is the reference for static export. Verified per "
            "renderer: a Rust coverage test, a rasterized-ink test, and three "
            "Chromium screenshots that hash differently per cap."
        ),
    ),
    MarkStyleProperty(
        id="border-radius",
        vocabulary="css",
        compiles_to="corner_radius",
        support={"webgl": "full", "svg": "full", "native": "full"},
        status="shipped",
        notes="Rect kinds only. `corner_radius=(tip, base)` rounds the two ends separately.",
    ),
    MarkStyleProperty(
        id="wedge-gap",
        vocabulary="xy",
        compiles_to="wedge_gap",
        support={"webgl": "full", "svg": "full", "native": "full"},
        status="shipped",
        notes=(
            "Gap between neighbouring polar wedges, in px. Rect kinds under "
            '`coords="polar"` only; ignored elsewhere. Deliberately a LENGTH '
            "rather than an angle: an angular pad's seam is `r * dtheta` wide, "
            "so it tapers to nothing at the hole and reads as uneven spacing. "
            "The angular inset therefore grows as the radius shrinks, which is "
            "the same construction as d3's padAngle/padRadius pair. An XY "
            "vocabulary name: CSS has no gap between two arcs."
        ),
    ),
    MarkStyleProperty(
        id="marker-shape",
        vocabulary="xy",
        compiles_to="symbol",
        support={"webgl": "full", "svg": "full", "native": "full"},
        status="shipped",
        notes=(
            "17 shapes, drawn as analytic signed-distance fields in all three "
            "renderers. An XY vocabulary name: CSS has no shape keyword for a "
            "non-DOM point mark, and the CSS spelling and `symbol=` compile to "
            "the same value."
        ),
    ),
)


#: Cross-renderer differences that exist in the *defaults* — no style property
#: selects them, so they are invisible until someone diffs two exports. They
#: belong in the registry for exactly that reason.
KNOWN_RENDERER_DIVERGENCES: tuple[RendererDivergence, ...] = (
    RendererDivergence(
        id="polyline_join_default",
        what="Interior vertices of a wide polyline",
        webgl="the notch two overlapping segment quads leave",
        svg="round (the writer names it explicitly)",
        native="round (the capsule distance field fills the vertex)",
        visible_when="stroke-width above ~4px at a sharp angle",
        tracked_by="no style property selects a join; the default is the whole contract",
    ),
    RendererDivergence(
        id="chrome_slot_title_stacking",
        what="A styled `chrome` slot background against the title text and the plot fill",
        webgl=(
            "the chrome canvas is appended AFTER the title divs "
            "(js/src/50_chartview.ts) and its CSS background paints under its "
            "own bitmap, so the backdrop covers titles and sits below --chart-bg"
        ),
        svg=(
            "one rect between the backgrounds and the grid group: above the "
            "root and plot fills, below every grid line and all chrome text"
        ),
        native="same seam as SVG (after the plot fill, before the plot clip)",
        visible_when=(
            "styles={'chrome': {'background': ...}} overlaps a title, or is "
            "combined with a --chart-bg plot fill"
        ),
        tracked_by=(
            "static-chrome-parity plan §3.5 pins the writers' seam; the DOM "
            "order is the browser's own stacking contract"
        ),
    ),
    RendererDivergence(
        id="title_entry_box_allowlist",
        what="Box styling authored on a per-entry title `style=` (not the title slot)",
        webgl=(
            "dropped: the client copies only color/font-family/font-size/"
            "font-style/font-weight from an entry's style onto the title div "
            "(js/src/50_chartview.ts entry-style allowlist)"
        ),
        svg="honored: `_title_metrics` merges entry style over the slot, box included",
        native="honored, same merge (the two writers share the title placement)",
        visible_when="xy.title(style={'background': ...}) or another per-entry box property",
        tracked_by=(
            "static-chrome-parity plan §3 acceptance records the divergence; "
            "slot-level `styles={'title': ...}` box declarations agree everywhere"
        ),
    ),
    RendererDivergence(
        id="annotation_layer_background_geometry",
        what="The annotation_layer slot's background extent",
        webgl="full-bleed (the overlay canvas is inset:0 over the whole chart)",
        svg="plot rect, inside the marks clip (the only seam above traces and below shapes)",
        native="plot rect, under the active marks clip (same seam as SVG)",
        visible_when="styles={'annotation_layer': {'background': ...}} is declared",
        tracked_by="tests/test_chrome_parity_p3.py pins the plot-rect geometry",
    ),
    RendererDivergence(
        id="labels_container_stacking",
        what="Where the labels-container background sits among its siblings (flag D)",
        webgl="over the chart title (the container is a later DOM sibling), "
        "under the axis rules and label texts it contains",
        svg="under the axis rules and label texts (the resolved flag-D order), "
        "and under the title/legend/colorbar chrome, which joins later",
        native="same as SVG: filled after the marks, before the chrome text phase",
        visible_when="styles={'labels': {'background': ...}} on a chart with a title, "
        "legend or colorbar",
        tracked_by="flag D of the static-chrome parity plan; "
        "tests/test_chrome_parity_p3.py pins the writers' order",
    ),
    RendererDivergence(
        id="annotation_layer_opacity_compositing",
        what="How the annotation_layer slot's opacity composites overlapping shapes",
        webgl="group opacity: the overlay canvas is dimmed once as a whole",
        svg="group opacity on the wrapping <g>, PDF-legal, same as live",
        native="folded into each shape's RGBA (no group compositing opcode): "
        "overlapping translucent shapes double-blend",
        visible_when="the slot declares opacity below 1 over overlapping annotation shapes",
        tracked_by="tests/test_chrome_parity_p3.py documents the double-blend delta",
    ),
    RendererDivergence(
        id="legend_slot_opacity_compositing",
        what="How a legend slot's `opacity` composites its box",
        webgl="group opacity: the element and its children fade once, together",
        svg="`opacity` on the box element, PDF-legal, same as live",
        native="premultiplied into the box's own RGBA (the display list has no "
        "group-compositing opcode), so a translucent frame does not also fade "
        "the swatches and labels drawn over it, and overlapping translucent "
        "boxes double-blend",
        visible_when="styles={'legend'|'legend_item'|'legend_swatch': {'opacity': <1}}",
        tracked_by=(
            "tests/test_chrome_parity_legend.py pins the premultiply; the raster "
            "opcode that would fix it needs the dual ABI bump (plan §9.9)"
        ),
    ),
    RendererDivergence(
        id="legend_frame_border_alpha_coupling",
        what="Whether the legend frame's alpha also dims its border (flag B)",
        webgl="one translucent element: the border fades with the fill",
        svg="`stroke-opacity` carries the frame alpha, matching live",
        native="the same alpha folded into the border RGBA",
        visible_when="the default grey frame, or --xy-legend-frame-alpha below 1",
        tracked_by=(
            "resolved in favor of the coupling when the frame folded onto the "
            "shared chrome-box lowering; ChromeBox.border_opacity carries it"
        ),
    ),
    RendererDivergence(
        id="axis_line_edge_geometry",
        what="Where an axis spine's box sits relative to the plot edge",
        webgl="right/bottom spines inset by their own width (DIVs laid inside the box)",
        svg="centered on the plot edge, where the unstyled stroke has always run",
        native="centered on the plot edge (same shared box producer as SVG)",
        visible_when="axis_width above ~2px, or a styled axis_line box under a magnifier",
        tracked_by=(
            "matching the browser would move every unstyled spine and break the "
            "byte pin; the writers' centered geometry is pinned by golden in "
            "tests/test_chrome_parity_p2.py"
        ),
    ),
)


#: What each slot's `styles={slot: ...}` reaches in the two native writers.
#: The writers now read a defined text/box subset for the slots that name
#: chrome a static file actually contains (`xy._svg.STATIC_STYLED_SLOTS`);
#: everything else is live-only chrome — a tooltip, a modebar, a crosshair —
#: and has nothing in a file to style.
_SLOT_SUBSET_NOTE = (
    "Vector (SVG, PDF) honors font-size, font-weight, font-style, font-family, "
    "letter-spacing, opacity and the text paint (`fill`, or `color`); PDF maps "
    "any declared family onto the base-14 Helvetica faces (regular/bold/"
    "oblique/bold-oblique), recorded in `_pdf.py`'s contract note. The raster "
    "atlas carries regular, bold and italic faces, so font-size, the paint, "
    "font-weight and font-style survive there too — font-family, "
    "letter-spacing and opacity remain vector-only rather than silently "
    "approximated. Properties outside the subset stay browser-only."
)

#: The box-vocabulary note shared by the P1 box slots (`_svg.SLOT_BOX_PROPS`,
#: drawn through the shared `_chromebox` lowering in both writers).
_SLOT_BOX_NOTE = (
    "Box slot: both writers honor background, border (color/width/style, "
    "dashed/dotted as dash arrays), symmetric border-radius, opacity and "
    "fill-opacity through the shared chrome-box lowering "
    "(`xy._chromebox.lower_box`); everything it cannot draw is a named loss "
    "in the preflight, never silent (§28)."
)

_SLOT_EXCEPTIONS: dict[str, tuple[str, str, str]] = {
    slot: ("partial", f"styles={{{slot!r}: ...}}", _SLOT_SUBSET_NOTE)
    for slot in STATIC_STYLED_SLOTS
}
_SLOT_EXCEPTIONS["legend"] = (
    "partial",
    "styles={'legend': ...} / xy.legend(style=...) / --chart-legend-bg",
    "The frame box, drawn through the shared chrome-box lowering "
    "(`xy._chromebox.lower_box`) in both writers. All three sources converge "
    "on one merged declaration before the writers see it, in the CSS and the "
    "camelCase spelling alike, so what agrees in the browser agrees in a PNG: "
    "`background`, `border-color`/`border-width`/`border-style`, "
    "`border-radius` (the authored value, not a pinned 4), `box-shadow`, "
    "`opacity`, `--xy-legend-frame-alpha`, and `padding`/`row-gap`/`gap` in "
    "resolved px or the legend's historical `em`. Padding and row-gap resize "
    "the frame in the exports, in pyplot's anchored-legend room reservation "
    "and in its best-location scoring together — one geometry, four "
    "consumers. An explicit background paints opaque, as it does in the "
    "browser, and `background: transparent` drops the frame entirely "
    "(Matplotlib `frameon=False`). A `box-shadow` carrying blur or spread "
    "draws the writers' offset-rect approximation and records the blur as a "
    "named loss (§28); the frame's alpha dims its border with it, matching "
    "the single translucent element the browser paints.",
)
_SLOT_EXCEPTIONS["legend_item"] = (
    "partial",
    "styles={'legend_item': ...}",
    "The per-row cell of the legend, one instance per visible entry, drawn "
    "under that row's swatch and label and over the frame and title. Box "
    "vocabulary only (`_svg.SLOT_BOX_PROPS`): the row has no text of its own, "
    "and its size comes from the legend layout, so `padding` is refused "
    "rather than accepted and ignored.",
)
_SLOT_EXCEPTIONS["legend_swatch"] = (
    "partial",
    "styles={'legend_swatch': ...}",
    "The handle cell of a legend row. On a patch entry the swatch IS the "
    "patch, so a declared background or border wins over the trace's own "
    "paint (browser precedence: the slot rule is applied after the per-entry "
    "paint variables) and a declared border-radius replaces the historical "
    "`rx=2`; on a marker or line entry the box paints behind the handle, "
    "which keeps its own ink. Box vocabulary only, padding excluded for the "
    "same reason as `legend_item`.",
)
_SLOT_EXCEPTIONS["title"] = (
    "partial",
    "styles={'title': ...}",
    _SLOT_SUBSET_NOTE + " The title also takes the full box vocabulary "
    "(`_svg.SLOT_BOX_PROPS`): a box under the text, sized to the measured "
    "block plus padding, with the title band growing to fit. Per-entry "
    "`xy.title(style=...)` box properties are native-only "
    "(KNOWN_RENDERER_DIVERGENCES `title_entry_box_allowlist`).",
)
_SLOT_EXCEPTIONS["root"] = (
    "partial",
    "styles={'root': ...} / chart style=",
    _SLOT_BOX_NOTE + " The root box is the figure patch: its fill replaces "
    "the `theme(background=)` token when both are set (same element, one "
    "background property, matching the browser), and an export "
    "`background=` override silences it (`_svg.apply_export_background` is "
    "the one precedence definition). box-shadow would fall outside the "
    "canvas and is a named loss; text properties have no root text to style. "
    "The chart-level `style=` token bag still reaches every renderer.",
)
_SLOT_EXCEPTIONS["chrome"] = (
    "partial",
    "styles={'chrome': ...}",
    "Background and opacity only (parity plan §8 flag G): one full-canvas "
    "backdrop above the root and plot fills, below the grid. The rest of the "
    "box vocabulary is a named preflight loss, and the browser's own "
    "stacking of this slot against titles diverges by design "
    "(KNOWN_RENDERER_DIVERGENCES `chrome_slot_title_stacking`).",
)
_SLOT_EXCEPTIONS["canvas"] = (
    "partial",
    "styles={'canvas': ...}",
    _SLOT_BOX_NOTE + " Painted at the above-grid seam, so a canvas "
    "background hides the grid exactly as the browser's marks canvas does; "
    "border-radius clips the marks through a dedicated clipPath in SVG/PDF "
    "and opacity rides the marks group there. The raster display list clips "
    "rectangles only and has no group compositing, so border-radius and "
    "opacity are named raster losses (`_svg.SLOT_BOX_RASTER_UNSUPPORTED`) "
    "until the rounded-clip opcode lands. An export `background=` override "
    "silences a canvas background like the plot token.",
)
_SLOT_EXCEPTIONS["labels"] = (
    "partial",
    "styles={'labels': ...}",
    "The label container. Its color is the default under the live chain "
    "`var(--chart-text, inherit)` for every contained text (tick labels, "
    "axis titles, annotation labels): the theme token wins, then the "
    "container color, then the writer default — the axis's own colors and "
    "the specific slots stay narrower and win. Typography folds under the "
    "contained slots exactly where the live stylesheet leaves the property "
    "un-ruled (font-size/weight cascade into tick labels only; style/family/"
    "letter-spacing into all three). `background` paints full-bleed under "
    "the axis rules and every label text, the live order; the residual "
    "sibling stacking difference is in KNOWN_RENDERER_DIVERGENCES. "
    "`opacity` rides the SVG label group (vector-only); live it also dims "
    "the contained axis rules and the container background — recorded here "
    "rather than approximated.",
)
_SLOT_EXCEPTIONS["annotation_layer"] = (
    "partial",
    "styles={'annotation_layer': ...}",
    "The annotation-shape overlay. `opacity` dims every annotation shape as "
    "a group (never the labels, which live in the labels container): SVG/PDF "
    "as real group opacity on a `<g>`, raster folded into each shape's RGBA "
    "because the display list has no group compositing — overlapping "
    "translucent shapes double-blend there, a recorded approximation (§28). "
    "`background` paints under the shapes, plot-clipped; the live overlay is "
    "full-bleed, a divergence recorded in KNOWN_RENDERER_DIVERGENCES. "
    "Everything else stays browser-only.",
)
_SLOT_EXCEPTIONS["annotation_label"] = (
    "partial",
    "styles={'annotation_label': ...}",
    "The per-slot text subset plus the shared chrome-box model "
    "(`xy._svg.SLOT_BOX_PROPS`): background, border — with solid/dashed/"
    "dotted lowered to a dash pattern and other border styles drawn solid "
    "and recorded (§28) — border-radius, CSS 1-4 value padding, offset "
    "box-shadow (blur/spread recorded unrepresentable), and whole-label "
    "opacity. The annotation's own `style=` is the narrower selector and "
    "wins per property group, matching the browser's slot-then-inline "
    "order. em font sizes resolve against the label's own 11px default. "
    "Vertical (rotation 90/270) labels keep only size and paint in SVG — "
    "a pre-existing limit of the rotated text path.",
)

#: The shared chrome-box vocabulary note, referenced by the axis-chrome slots
#: below. The vocabulary itself is `xy._svg.SLOT_BOX_PROPS` (writer-owned, the
#: preflight reads the same constant).
_BOX_VOCAB_NOTE = (
    "background, border (color/width/style, dashed/dotted as dash arrays), "
    "symmetric border-radius, offset box-shadow (blur/spread recorded "
    "unrepresentable), opacity and fill-opacity"
)
_SLOT_EXCEPTIONS["axis_line"] = (
    "partial",
    "styles={'axis_line': ...}",
    "Spines as boxes when box properties are declared: " + _BOX_VOCAB_NOTE + ". "
    "The spine keeps its axis_color ink unless the slot declares a background "
    "(an explicit transparent erases it, as in the browser). Writers center "
    "the box on the plot edge where the unstyled stroke ran; the browser "
    "insets right/bottom spines (see KNOWN_RENDERER_DIVERGENCES). Polar "
    "spines stay strokes — the browser shares the limit (DIV spines cannot "
    "express a circle).",
)
_SLOT_EXCEPTIONS["tick_mark"] = (
    "partial",
    "styles={'tick_mark': ...}",
    "Tick marks as boxes when box properties are declared: " + _BOX_VOCAB_NOTE + ". "
    "Geometry is the centered stroke's own coverage — the same pixels as the "
    "browser's rect. Marks exist only where an axis authors tick_length > 0; "
    "a zero-length tick draws nothing (and casts no shadow) — the preflight "
    "carries the note rather than a length being invented. tick_color stays "
    "the narrower paint selector; polar has no cartesian tick marks "
    "(recorded).",
)
_SLOT_EXCEPTIONS["tick_label"] = (
    "partial",
    "styles={'tick_label': ...}",
    _SLOT_SUBSET_NOTE + " Additionally a per-label box: " + _BOX_VOCAB_NOTE + ", "
    "with padding growing the axis gutters so the box stays on the canvas "
    "(cartesian; the polar label ring keeps its flat 30px allowance). Box "
    "geometry is measured with the writers' DejaVu metrics, so an authored "
    "font-family renders its own glyphs inside a DejaVu-measured box "
    "(recorded misfit); letter-spacing is likewise outside the gutter "
    "measurement. On the raster writer a declared opacity reaches the box, "
    "not the glyphs (the atlas blit has no alpha channel).",
)
_SLOT_EXCEPTIONS["axis_title"] = (
    "partial",
    "styles={'axis_title': ...}",
    _SLOT_SUBSET_NOTE + " Additionally a per-title box: " + _BOX_VOCAB_NOTE + "; "
    "a rotated y-title box is pre-rotated to a polygon (radius 0) or an "
    "arc path (radius > 0), staying inside the PDF closed subset. The axis's "
    "own label_* keys win per property over the slot (label_color, "
    "label_font_family/style/weight); font-size runs the other way — the "
    "slot's font-size wins over label_size (pre-existing, documented in "
    "spec/api/styling.md). DejaVu-measured box vs authored-family text and "
    "raster box-not-glyph opacity are recorded exactly as for tick_label.",
)


#: The state that gates each live-only slot. Listed explicitly, one entry per
#: slot rather than by prefix, so `tests/test_capability_registry.py` can
#: assert the partition covers `CHART_DOM_SLOTS` exactly and that every member
#: of a chrome family carries its family's state — a new `modebar_*` slot that
#: forgets its entry fails the suite instead of quietly counting as static.
_STATE_GATED_SLOTS: dict[str, str] = {
    "tooltip": "hover",
    "tooltip_title": "hover",
    "tooltip_row": "hover",
    "tooltip_label": "hover",
    "tooltip_value": "hover",
    "modebar": "modebar",
    "modebar_drag_handle": "modebar",
    "modebar_control_group": "modebar",
    "modebar_separator": "modebar",
    "modebar_button": "modebar",
    "modebar_icon": "modebar",
    "modebar_zoom_value": "modebar",
    "modebar_indicator": "modebar",
    "modebar_selection_icon": "modebar",
    "modebar_menu": "modebar",
    "modebar_menu_separator": "modebar",
    "modebar_menu_icon": "modebar",
    "modebar_menu_label": "modebar",
    "modebar_history_controls": "modebar",
    "selection": "selection",
    "crosshair_x": "crosshair",
    "crosshair_y": "crosshair",
    "badge": "view",
    "badge_item": "view",
    # Flag-F resolution (static-chrome-parity plan §8): the browser creates
    # the band only when its axis is navigable (`57_viewstate.ts
    # _axisBandNavigable`) — pan/zoom chrome, not structure — and a static
    # file has no gesture for it to serve, so it follows the badge precedent
    # (interaction-gated, no writer emission) rather than the earlier
    # capability-matrix "clean static" row. Deemed structural again only by
    # a spec decision, never by a writer quietly drawing it.
    "axis_band": "navigation",
}


CHART_SLOTS: tuple[SlotCapability, ...] = tuple(
    SlotCapability(
        id=slot,
        support={
            "browser": "full",
            "native_raster": _SLOT_EXCEPTIONS.get(slot, ("none",))[0],
            "native_vector": _SLOT_EXCEPTIONS.get(slot, ("none",))[0],
        },
        channel=_SLOT_EXCEPTIONS[slot][1] if slot in _SLOT_EXCEPTIONS else "",
        notes=_SLOT_EXCEPTIONS[slot][2] if slot in _SLOT_EXCEPTIONS else "",
        applicability=_STATE_GATED_SLOTS.get(slot, "static"),
    )
    for slot in CHART_DOM_SLOTS
)


#: Ways to add behavior the core does not ship. This is the leg XY lost
#: outright before `xy.register_mark` existed, and the honest entry is still
#: narrower than Matplotlib's custom `Artist`.
EXTENSION_POINTS: tuple[ExtensionPoint, ...] = (
    ExtensionPoint(
        id="mark_plugin_composition",
        status="shipped",
        entry_point="xy.register_mark / xy.MarkPlugin / xy.mark",
        notes=(
            "A calc over declared columns plus a build that returns built-in "
            "marks. Its output is ordinary traces, so it reuses the built-in "
            "rendering, picking, and export paths rather than reimplementing "
            "them."
        ),
        limits=(
            "composes built-in marks only, one level deep",
            "cannot reach the Figure, the trace list, or the column store",
            "cannot add a GPU primitive",
        ),
    ),
    ExtensionPoint(
        id="mark_plugin_shader",
        status="planned",
        entry_point="",
        notes=(
            "§24's WGSL/GLSL snippet pair. Deferred: a plugin with its own "
            "shader reuses none of the built-in rendering, picking, or export "
            "paths and would have to reimplement them."
        ),
        limits=(),
    ),
    ExtensionPoint(
        id="custom_renderer",
        status="planned",
        entry_point="",
        notes="No way to add a fourth renderer or replace one of the three.",
        limits=(),
    ),
)


def markdown_mark_property_table(
    properties: Iterable[MarkStyleProperty] = MARK_STYLE_PROPERTIES,
) -> list[str]:
    """One row per style property, with its per-renderer support."""
    lines = [
        "| property | vocabulary | mark kinds | webgl | svg | native | status |",
        "|---|---|---|---|---|---|---|",
    ]
    for prop in properties:
        kinds = ", ".join(f"`{kind}`" for kind in prop.kinds) or "—"
        lines.append(
            f"| `{prop.id}` | {prop.vocabulary} | {kinds} | "
            f"{prop.support['webgl']} | {prop.support['svg']} | "
            f"{prop.support['native']} | {prop.status} |"
        )
    return lines


def markdown_slot_table(slots: Iterable[SlotCapability] = CHART_SLOTS) -> list[str]:
    """One row per chrome slot, with how far its styling travels."""
    lines = [
        "| slot | applicable in | browser | native raster | native vector |",
        "|---|---|---|---|---|",
    ]
    for slot in slots:
        applicable = (
            "clean static" if slot.applicability == "static" else f"{slot.applicability} state"
        )
        lines.append(
            f"| `{slot.id}` | {applicable} | {slot.support['browser']} | "
            f"{slot.support['native_raster']} | {slot.support['native_vector']} |"
        )
    return lines


def markdown_extension_table(points: Iterable[ExtensionPoint] = EXTENSION_POINTS) -> list[str]:
    """One row per extension point, with its declared limits."""
    lines = ["| extension point | status | entry point | limits |", "|---|---|---|---|"]
    for point in points:
        limits = "; ".join(point.limits) or "—"
        lines.append(f"| {point.id} | {point.status} | `{point.entry_point or '—'}` | {limits} |")
    return lines


def axis_style_keys() -> tuple[str, ...]:
    """The axis `style=` vocabulary, read from `styles.py` rather than listed.

    A fresh-agent evaluation of this repo caught the comparison document
    quoting 15 of these after a 16th shipped. Prose cannot hold a count; the
    registry derives it and `summary()` publishes it.
    """
    return tuple(
        sorted(
            styles._AXIS_COLOR_PROPERTIES
            | styles._AXIS_FONT_PROPERTIES
            | styles._AXIS_LENGTH_PROPERTIES
            | styles._AXIS_SIZE_PROPERTIES
            | styles._AXIS_COMPAT_PROPERTIES
            | {"tick_direction", "tick_label_anchor"}
        )
    )


def summary() -> dict[str, object]:
    """Counts a release note can quote without anyone recounting by hand."""
    shipped = [p for p in MARK_STYLE_PROPERTIES if p.status == "shipped"]
    static = [s for s in CHART_SLOTS if s.applicability == "static"]
    return {
        "axis_style_keys": len(axis_style_keys()),
        "mark_style_properties": len(MARK_STYLE_PROPERTIES),
        "mark_style_properties_shipped": len(shipped),
        "mark_kinds": len(styles._MARK_KINDS),
        "chart_slots": len(CHART_SLOTS),
        "chart_slots_static": len(static),
        "chart_slots_state_gated": len(CHART_SLOTS) - len(static),
        "static_slots_native": sum(1 for s in static if s.support["native_raster"] != "none"),
        "slots_styleable_natively": sum(
            1 for s in CHART_SLOTS if s.support["native_raster"] != "none"
        ),
        # The `styles={slot: ...}` channel specifically — the writers' own
        # STATIC_STYLED_SLOTS, counted from the registry so generated prose
        # cannot hold a stale number (the axis_style_keys lesson).
        "slots_via_styles": sum(1 for s in CHART_SLOTS if s.channel.startswith("styles={")),
        "extension_points_shipped": sum(1 for e in EXTENSION_POINTS if e.status == "shipped"),
        "known_renderer_divergences": len(KNOWN_RENDERER_DIVERGENCES),
    }


__all__ = [
    "APPLICABILITIES",
    "CHART_SLOTS",
    "EXPORT_STATES",
    "EXTENSION_POINTS",
    "KNOWN_RENDERER_DIVERGENCES",
    "MARK_STYLE_PROPERTIES",
    "RENDERERS",
    "SURFACES",
    "ExtensionPoint",
    "MarkStyleProperty",
    "RendererDivergence",
    "SlotCapability",
    "axis_style_keys",
    "markdown_extension_table",
    "markdown_mark_property_table",
    "markdown_slot_table",
    "summary",
]
