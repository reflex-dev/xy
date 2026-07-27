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
)


#: Slots whose styling reaches the native writers through some channel other
#: than `styles={slot: ...}`, which none of them read. Everything else is
#: browser-only, and that is the answer for 22 of the 23.
_SLOT_EXCEPTIONS: dict[str, tuple[str, str, str]] = {
    "legend": (
        "partial",
        "xy.legend(style=...)",
        "Written twice: to chrome_styles for the browser and to "
        "legend_options['style'], which `_svg` and `_raster` do read — but only "
        "`background`, `boxShadow`, `borderRadius`, `--xy-legend-frame-alpha`, "
        "and `padding`/`rowGap` in `em`. The chart-level styles={'legend': ...} "
        "spelling reaches none of it, so two spellings that agree in the browser "
        "disagree in a PNG.",
    ),
    "root": (
        "partial",
        "chart style=",
        "`styles={'root': ...}` is browser-only, but the chart-level `style=` "
        "token bag targets the same element and every renderer reads it "
        "(`spec['dom']['style']`). Prefer it for anything that must survive "
        "export.",
    ),
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
        "| slot | browser | native raster | native vector |",
        "|---|---|---|---|",
    ]
    for slot in slots:
        lines.append(
            f"| `{slot.id}` | {slot.support['browser']} | "
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
    return {
        "axis_style_keys": len(axis_style_keys()),
        "mark_style_properties": len(MARK_STYLE_PROPERTIES),
        "mark_style_properties_shipped": len(shipped),
        "mark_kinds": len(styles._MARK_KINDS),
        "chart_slots": len(CHART_SLOTS),
        "slots_styleable_natively": sum(
            1 for s in CHART_SLOTS if s.support["native_raster"] != "none"
        ),
        "extension_points_shipped": sum(1 for e in EXTENSION_POINTS if e.status == "shipped"),
        "known_renderer_divergences": len(KNOWN_RENDERER_DIVERGENCES),
    }


__all__ = [
    "CHART_SLOTS",
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
