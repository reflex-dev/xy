"""The shared chrome-box model: one lowering, two emitters, zero drift.

Static-chrome parity gives every applicable slot a real box (background,
border, radius, shadow, opacity) in both native writers. The three box
drawers that existed before this module — the legend frame, the annotation
text box, and the background composition — were each written twice and
drifted twice (hard-coded shadow constants, different radius geometry);
this module is the single lowering from a resolved declaration to a
`ChromeBox`, consumed by `_svg._slot_box_svg` and `_raster._emit_slot_box`
so a box drawn in one writer cannot mean something else in the other.

Contract notes, each load-bearing:

- Values are resolved px/colors (the snapshot contract); the lowering
  parses spellings, it never resolves cascades.
- `radius` is one symmetric `rx` clamped to `min(w, h) / 2` — PDF accepts
  `rx` and rejects `ry` (probe-verified), so asymmetric corner radii are
  outside the model until a path lowering exists.
- `shadow` is the offset-rect approximation this codebase has always drawn
  (no blur primitive exists in the raster opcodes and PDF rejects
  `filter`); a blur/spread request is recorded in `unrepresentable`, never
  silently blurless (§28).
- `border-style` lowers `dashed`/`dotted` to dash arrays scaled by width —
  the same construction both writers already use for data strokes; `double`
  and friends are recorded unrepresentable.
- A rotated box (`angle` about `(cx, cy)`) is lowered by the emitters to
  pre-rotated geometry — a polygon when `radius == 0`, a path with circular
  arcs when `radius > 0` — because the PDF closed subset accepts no
  `transform` on `<rect>`. One lowering repo-wide (plan flag E).
- A zero-area box emits nothing at all — no fill, no border, and explicitly
  no shadow (a `tick_length: 0` tick must not cast one).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import Any, Optional

__all__ = [
    "ChromeBox",
    "box_at",
    "box_padding",
    "box_room",
    "box_template",
    "expand_box_shorthands",
    "lower_box",
    "padding_sides",
    "parse_padding",
    "rotate_points",
    "text_box",
]


def rotate_points(
    points: list[tuple[float, float]], angle: float, cx: float, cy: float
) -> list[tuple[float, float]]:
    """Points rotated `angle` degrees (screen space, y down) about `(cx, cy)`.

    The one rotation both emitters use to pre-rotate a posed box — the PDF
    subset accepts no transform on shapes, and the raster display list has no
    transform primitive, so rotation happens here, once, in Python.
    """
    radians = math.radians(angle)
    cos, sin = math.cos(radians), math.sin(radians)
    return [
        (cx + (px - cx) * cos - (py - cy) * sin, cy + (px - cx) * sin + (py - cy) * cos)
        for px, py in points
    ]


_LENGTH_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)(?:px)?\s*$")

_BORDER_STYLES = frozenset(
    {"solid", "dashed", "dotted", "none", "hidden", "double", "groove", "ridge", "inset", "outset"}
)


@dataclass(frozen=True)
class ChromeBox:
    """One slot instance's resolved box, ready for either writer.

    `qualifiers` is the instance's stable identity beyond the slot name
    (`SlotInstance.qualifiers` carrier — e.g. `("x", "major", "bottom", "3")`
    for a tick mark). `angle`/`cx`/`cy` is the rotation pose (an axis
    y-title); zero for most slots.
    """

    slot: str
    x: float
    y: float
    w: float
    h: float
    fill: Optional[str] = None  # resolved CSS color text, writer-parsed
    fill_opacity: float = 1.0
    border_color: Optional[str] = None
    border_width: float = 0.0
    border_dash: Optional[tuple[float, ...]] = None
    radius: float = 0.0
    shadow: Optional[tuple[float, float, str]] = None  # (dx, dy, color)
    opacity: float = 1.0
    # (top, right, bottom, left) px. Consumed by the layout/room functions
    # that size the box around its content — never by the emitters, which
    # draw exactly the (x, y, w, h) they are given.
    padding: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    #: Pyplot text-bbox compatibility: the pre-parity SVG emitter serialized
    #: `stroke=... stroke-width=...` on every bbox rect, including the inert
    #: `stroke="none" stroke-width="0"` of a borderless box, and existing
    #: pyplot output is byte-pinned (§0.5). An adapter folding that emitter
    #: onto this model sets `(paint, width)` here so the SVG writer keeps
    #: those exact attributes when no active border exists; the raster twin
    #: ignores it, because the raster writer never painted a zero-width
    #: border. New chrome boxes leave it None.
    explicit_stroke: Optional[tuple[str, float]] = None
    unrepresentable: tuple[str, ...] = field(default_factory=tuple)
    qualifiers: tuple[str, ...] = ()
    angle: float = 0.0
    cx: float = 0.0
    cy: float = 0.0
    #: True when the declaration carried a `background`/`background-color`
    #: key at all — an explicit `transparent` (fill None, declared True) must
    #: not fall back to a slot's default ink the way an absent key does.
    fill_declared: bool = False

    @property
    def paints_anything(self) -> bool:
        if self.w <= 0.0 or self.h <= 0.0:
            return False
        return self.fill is not None or (self.border_color is not None and self.border_width > 0)


def parse_padding(value: Any) -> Optional[tuple[float, float, float, float]]:
    """CSS `padding` shorthand as `(top, right, bottom, left)` px, or None.

    Accepts 1-4 px lengths with the standard CSS expansion. The existing
    annotation-box parsers read tokens [0]/[1] only, which silently misreads
    a 4-value shorthand — this is the one correct expansion every box
    consumer shares.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = float(value)
        return (v, v, v, v)
    if not isinstance(value, str):
        return None
    tokens = value.split()
    if not 1 <= len(tokens) <= 4:
        return None
    sides = [_px(token) for token in tokens]
    if any(side is None for side in sides):
        return None
    vals = [float(side) for side in sides if side is not None]
    if len(vals) == 1:
        vals *= 4
    elif len(vals) == 2:
        vals = [vals[0], vals[1], vals[0], vals[1]]
    elif len(vals) == 3:
        vals = [vals[0], vals[1], vals[2], vals[1]]
    return (vals[0], vals[1], vals[2], vals[3])


def padding_sides(declaration: Optional[dict[str, Any]]) -> tuple[float, float, float, float]:
    """A declaration's padding as `(top, right, bottom, left)` px.

    The `padding` shorthand seeds all four sides; a `padding-*` longhand
    overrides its side regardless of dict order (documented precedence — the
    resolver has no declaration order to honor).
    """
    if not declaration:
        return (0.0, 0.0, 0.0, 0.0)
    sides = list(parse_padding(declaration.get("padding")) or (0.0, 0.0, 0.0, 0.0))
    for index, prop in enumerate(
        ("padding-top", "padding-right", "padding-bottom", "padding-left")
    ):
        longhand = _px(declaration.get(prop))
        if longhand is not None:
            sides[index] = longhand
    return (sides[0], sides[1], sides[2], sides[3])


def _border_width(declaration: dict[str, Any]) -> float:
    """The border width lower_box would draw — one rule, shared with rooms."""
    width = _px(declaration.get("border-width")) or 0.0
    style = str(declaration.get("border-style", "solid") or "solid").strip().lower()
    if style in ("none", "hidden"):
        return 0.0
    if declaration.get("border-color") is not None and width == 0.0:
        return 1.0  # the 1px chrome-border default, mirroring lower_box
    return width


def box_room(declaration: Optional[dict[str, Any]]) -> tuple[float, float, float, float]:
    """Outward growth `(top, right, bottom, left)` a declared box adds around
    its content: per-side padding plus the border width. The layout/room
    functions consume this; the emitters never do (geometry already carries
    it)."""
    if not declaration:
        return (0.0, 0.0, 0.0, 0.0)
    top, right, bottom, left = padding_sides(declaration)
    border = _border_width(declaration)
    return (top + border, right + border, bottom + border, left + border)


def box_template(slot: str, declaration: dict[str, Any]) -> ChromeBox:
    """The declaration lowered once, geometry-free — the interning half.

    A dense axis draws one declaration N times; parsing it per instance is
    the cost `styling/resolved.py`'s interning design exists to avoid. The
    huge placeholder geometry keeps the radius unclamped so `box_at` can
    clamp per instance.
    """
    return lower_box(slot, declaration, x=0.0, y=0.0, w=1e18, h=1e18)


def box_at(
    template: ChromeBox,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    qualifiers: tuple[str, ...] = (),
    angle: float = 0.0,
    cx: float = 0.0,
    cy: float = 0.0,
    fallback_fill: Optional[str] = None,
) -> ChromeBox:
    """One instance of an interned template at a concrete geometry.

    `fallback_fill` is the slot's default ink (an axis spine's `axis_color`);
    it applies only when the declaration never mentioned a background — an
    explicit `transparent` stays unpainted, exactly as in the browser.
    """
    fill = template.fill
    if fill is None and not template.fill_declared and fallback_fill is not None:
        fill = fallback_fill
    radius = max(0.0, min(template.radius, w / 2.0, h / 2.0)) if w > 0.0 and h > 0.0 else 0.0
    return replace(
        template,
        x=float(x),
        y=float(y),
        w=float(w),
        h=float(h),
        fill=fill,
        radius=radius,
        qualifiers=tuple(str(q) for q in qualifiers),
        angle=float(angle),
        cx=float(cx),
        cy=float(cy),
    )


def text_box(
    template: ChromeBox,
    pads: tuple[float, float, float, float],
    *,
    x: float,
    y: float,
    anchor: str,
    block: Any,
    angle: float = 0.0,
    qualifiers: tuple[str, ...] = (),
) -> ChromeBox:
    """The box around one text block, in the writers' shared metrics.

    `(x, y)` is the text anchor (first-line baseline), `anchor` the SVG
    vocabulary (`start`/`middle`/`end`), `block` a `_textblock.TextBlock`.
    Padding is applied in text-local space; a rotated label's box rotates
    with the text about the anchor — the emitters lower that pose to
    PDF-legal pre-rotated geometry. Both writers build tick-label and
    axis-title boxes through here, so their geometry cannot drift (the
    metrics are the writers' DejaVu tables; an authored font-family renders
    other glyphs inside a DejaVu-measured box — recorded misfit, §28).
    """
    pad_t, pad_r, pad_b, pad_l = pads
    if anchor == "middle":
        x0 = x - block.width / 2.0
    elif anchor == "end":
        x0 = x - block.width
    else:
        x0 = x
    y0 = y - block.ascent
    height = block.ascent + block.descent + (block.line_count - 1) * block.line_step
    return box_at(
        template,
        x0 - pad_l,
        y0 - pad_t,
        block.width + pad_l + pad_r,
        height + pad_t + pad_b,
        qualifiers=qualifiers,
        angle=angle,
        cx=x,
        cy=y,
    )


def _px(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = _LENGTH_RE.match(value)
        if m:
            return float(m.group(1))
    return None


def _opacity(value: Any, fallback: float = 1.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return fallback
    return min(1.0, max(0.0, out))


def _border_dash(style: str, width: float) -> Optional[tuple[float, ...]]:
    if style == "dashed":
        return (3.7 * width, 1.6 * width)
    if style == "dotted":
        return (width, width)
    return None


def _parse_shadow(value: str) -> tuple[Optional[tuple[float, float, str]], Optional[str]]:
    """`box-shadow` to the offset-rect model, or the reason it cannot be.

    Accepted: `<dx> <dy> [color]` and `<dx> <dy> 0 [0] [color]` (explicit
    zero blur/spread). Anything with real blur/spread, insets, or multiple
    shadows is unrepresentable in the offset-rect model.
    """
    text = value.strip()
    if not text or text == "none":
        return None, None
    # Multiple shadows split on top-level commas; a color's own commas
    # (rgba(0, 0, 0, .2)) live inside parens and must not count.
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            return None, "multiple shadows"
    if "inset" in text:
        return None, "inset shadow"
    parts: list[str] = []
    depth = 0
    token = ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch.isspace() and depth == 0:
            if token:
                parts.append(token)
                token = ""
        else:
            token += ch
    if token:
        parts.append(token)
    lengths: list[float] = []
    color = ""
    for part in parts:
        px = _px(part)
        if px is not None and not color:
            lengths.append(px)
        else:
            color = f"{color} {part}".strip()
    if len(lengths) < 2:
        return None, "shadow needs dx and dy"
    if any(v != 0.0 for v in lengths[2:4]):
        return None, "shadow blur/spread (no blur primitive in the native writers)"
    return (lengths[0], lengths[1], color or "rgba(0, 0, 0, 0.22)"), None


def _padding_sides(value: Any) -> Optional[tuple[float, float, float, float]]:
    """A CSS `padding` shorthand as (top, right, bottom, left), or None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        px = float(value)
        return (px, px, px, px)
    if not isinstance(value, str):
        return None
    parts = [_px(token) for token in value.split()]
    if not 1 <= len(parts) <= 4 or any(px is None for px in parts):
        return None
    sides = [float(px) for px in parts if px is not None]
    top = sides[0]
    right = sides[1] if len(sides) > 1 else top
    bottom = sides[2] if len(sides) > 2 else top
    left = sides[3] if len(sides) > 3 else right
    return (top, right, bottom, left)


def expand_box_shorthands(declaration: dict[str, Any]) -> dict[str, Any]:
    """Split the box shorthands (`border`, `padding`) into their longhands.

    Same policy as the cascade extension's `_expand_shorthands`: an explicit
    longhand beside the shorthand wins (it is the narrower author intent).
    A shorthand this parser cannot split — an em `padding`, a `border` with
    no recognizable parts — is passed through untouched so nothing declared
    disappears; the consumer decides what an unexpanded value means.
    """
    out: dict[str, Any] = {}
    for prop, value in declaration.items():
        if prop == "padding":
            sides = _padding_sides(value)
            if sides is not None:
                for name, side in zip(
                    ("padding-top", "padding-right", "padding-bottom", "padding-left"),
                    sides,
                    strict=True,
                ):
                    if name not in declaration:
                        out.setdefault(name, side)
                continue
        if prop == "border" and isinstance(value, str):
            width: Optional[float] = None
            style: Optional[str] = None
            color_parts: list[str] = []
            for token in value.split():
                token_px = _px(token)
                if token_px is not None and width is None:
                    width = token_px
                elif token.lower() in _BORDER_STYLES and style is None:
                    style = token.lower()
                else:
                    color_parts.append(token)
            if width is not None or style is not None or color_parts:
                if width is not None and "border-width" not in declaration:
                    out.setdefault("border-width", width)
                if style is not None and "border-style" not in declaration:
                    out.setdefault("border-style", style)
                if color_parts and "border-color" not in declaration:
                    out.setdefault("border-color", " ".join(color_parts))
                continue
        out[prop] = value
    return out


def box_padding(declaration: dict[str, Any]) -> tuple[float, float, float, float]:
    """A declaration's resolved padding as (top, right, bottom, left) px.

    Longhands win over the shorthand; anything unparsable (em values stay
    the legend writers' domain until P4) contributes zero rather than a
    guess.
    """
    expanded = expand_box_shorthands(declaration)
    top, right, bottom, left = (
        float(_px(expanded.get(name)) or 0.0)
        for name in ("padding-top", "padding-right", "padding-bottom", "padding-left")
    )
    return (top, right, bottom, left)


def lower_box(
    slot: str,
    declaration: dict[str, Any],
    *,
    x: float,
    y: float,
    w: float,
    h: float,
) -> ChromeBox:
    """Lower one resolved declaration onto a geometry rectangle.

    Reads only the box vocabulary; text properties ride the existing text
    emitters. Every request the model cannot draw lands in
    `unrepresentable` with its reason — the preflight and the tests read
    that list, so nothing rounds to silence.
    """
    unrepresentable: list[str] = []
    declaration = expand_box_shorthands(declaration)

    fill_declared = "background" in declaration or "background-color" in declaration
    fill = declaration.get("background")
    if fill is None:
        fill = declaration.get("background-color")
    if isinstance(fill, str) and ("gradient(" in fill or "url(" in fill):
        unrepresentable.append(f"background {fill!r} (box gradients land with the effect phase)")
        fill = None
    if fill is not None and not isinstance(fill, str):
        fill = str(fill)
    if isinstance(fill, str) and fill.strip().lower() in ("", "none", "transparent"):
        fill = None

    border_width = _px(declaration.get("border-width")) or 0.0
    border_color = declaration.get("border-color")
    border_style = str(declaration.get("border-style", "solid") or "solid").strip().lower()
    if border_color is not None and border_width == 0.0:
        border_width = 1.0  # CSS medium is 3px, but chrome borders here have always drawn 1px
    if border_style in ("none", "hidden"):
        border_color, border_width = None, 0.0
        dash = None
    elif border_style in ("solid", "dashed", "dotted"):
        dash = _border_dash(border_style, max(border_width, 1.0))
    else:
        unrepresentable.append(f"border-style {border_style!r}")
        dash = None
    if border_color is not None:
        border_color = str(border_color)

    radius = _px(declaration.get("border-radius")) or 0.0
    if (
        isinstance(declaration.get("border-radius"), str)
        and " " in str(declaration["border-radius"]).strip()
    ):
        unrepresentable.append(
            "asymmetric border-radius (PDF accepts symmetric rx only; path lowering pending)"
        )
        radius = 0.0
    radius = max(0.0, min(radius, w / 2.0, h / 2.0))

    shadow = None
    raw_shadow = declaration.get("box-shadow")
    if isinstance(raw_shadow, str):
        shadow, why = _parse_shadow(raw_shadow)
        if why is not None:
            unrepresentable.append(f"box-shadow: {why}")

    return ChromeBox(
        slot=slot,
        x=float(x),
        y=float(y),
        w=float(w),
        h=float(h),
        fill=fill,
        fill_opacity=_opacity(declaration.get("fill-opacity"), 1.0),
        border_color=border_color,
        border_width=border_width,
        border_dash=dash,
        radius=radius,
        shadow=shadow,
        opacity=_opacity(declaration.get("opacity"), 1.0),
        padding=box_padding(declaration),
        unrepresentable=tuple(unrepresentable),
        fill_declared=fill_declared,
    )
