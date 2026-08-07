"""The declared-styling resolver: a figure's authored chrome styling as a
`ResolvedStyleSnapshot`, beside the byte-exact view the writers consume.

This is the Python half of the two-resolver architecture (`resolved.py`
module docstring): the browser capture resolves the *computed* cascade; this
module resolves what the chart *declared* — per-slot `styles=`, normalized
to the writers' kebab-case spelling, interned per distinct declaration.

Two outputs, one construction, deliberately separate:

- `slot_view()` is the mapping the static writers read — byte-for-byte the
  old `_svg.slot_styles` result, authored objects preserved (an authored
  `600` stays `int`, so emitted attributes keep their exact spelling).
- `snapshot` is the same declared content as IR: every schema-legal value
  interned (numbers as floats, per the wire contract). New consumers — the
  snapshot export path, capability tooling, the capture diff — read this.

The divergence between the two is presentational number formatting plus the
values schema v1 refuses outright — today, exactly the relative-unit
lengths (`0.08em`), which are a document dependency the snapshot may not
carry (`resolved._RELATIVE_UNITS`). Those land in `writer_domain`, so
nothing declared is dropped in either direction and the gap is enumerable.

The legend used to add a second, slot-specific residue on top of that: its
geometry ran in em multipliers ONLY (`padding`/`row-gap`/`font-size`), so an
author who wanted a legend measured in pixels had no spelling that worked
and every legend geometry declaration was writer-domain by construction.
The static-chrome-parity P4 family retired it — `_svg._legend_length` and
`_svg._legend_padding` resolve px and em alike, so the px spelling interns
into the snapshot like any other resolved length and only a genuinely
relative value stays writer-domain, for the same reason every other slot's
does. `row-gap` is the one remaining wrinkle and it is a vocabulary
question, not a legend one: schema v1 carries `gap` but not `row-gap`
(`resolved.LAYOUT_PROPERTIES_V1`), so a px `row-gap` is writer-domain until
the schema grows one, while the equivalent px `gap` interns.
`tests/test_declared_snapshot.py` pins the view equivalence and enumerates
whatever residue is genuinely left.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from ..dom import CHART_DOM_SLOTS
from .resolved import ResolvedStyleSnapshot, SnapshotBuilder, SnapshotEnvironment, assert_resolved

#: Slots whose snapshot instances carry per-instance qualifiers + geometry,
#: produced by the writers' own `axis_chrome_boxes` (one geometry source for
#: the SVG writer, the raster writer, and this snapshot). The rest of the
#: axis family joins as its per-instance identity becomes load-bearing.
_PER_INSTANCE_SLOTS: tuple[str, ...] = ("axis_line", "tick_mark")

#: Re-entrancy guard for the per-instance producer: `axis_chrome_boxes` runs
#: `_svg.layout`, whose title measurement calls back into `resolve_declared`.
#: The nested resolution only needs the writer view, so it skips instance
#: production instead of recursing.
_INSTANCE_GUARD = threading.local()


def _axis_instance_records(
    spec: dict[str, Any], view: dict[str, dict[str, Any]]
) -> dict[str, list[tuple[tuple[str, ...], tuple[float, float, float, float]]]]:
    """Per-instance (qualifiers, geometry) records for the axis box slots."""
    if getattr(_INSTANCE_GUARD, "active", False):
        return {}
    if "x_axis" not in spec or "y_axis" not in spec:
        return {}  # a bare styling spec has no layout to resolve against
    from .._svg import _has_box_declaration, axis_chrome_boxes

    if not any(_has_box_declaration(view.get(slot)) for slot in _PER_INSTANCE_SLOTS):
        return {}
    _INSTANCE_GUARD.active = True
    try:
        boxes = axis_chrome_boxes(spec, view)
    finally:
        _INSTANCE_GUARD.active = False
    records: dict[str, list[tuple[tuple[str, ...], tuple[float, float, float, float]]]] = {}
    for box in boxes:
        records.setdefault(box.slot, []).append((box.qualifiers, (box.x, box.y, box.w, box.h)))
    return records


@dataclass(frozen=True)
class DeclaredStyling:
    """A figure's declared chrome styling: writer view + IR snapshot."""

    snapshot: ResolvedStyleSnapshot
    writer_domain: dict[str, dict[str, Any]] = field(default_factory=dict)
    _view: dict[str, dict[str, Any]] = field(default_factory=dict)

    def slot_view(self) -> dict[str, dict[str, Any]]:
        """The writers' mapping — identical to the pre-IR `slot_styles`."""
        return {slot: dict(decls) for slot, decls in self._view.items()}


def _kebab(name: object) -> str:
    text = str(name)
    return text if text.startswith("--") else text.replace("_", "-")


def resolve_declared(
    spec: dict[str, Any],
    *,
    width: Optional[float] = None,
    height: Optional[float] = None,
) -> DeclaredStyling:
    """Resolve `spec`'s per-slot declarations into view + snapshot.

    View normalization is byte-for-byte the old `_svg.slot_styles` rule —
    kebab-case property spelling, custom properties untouched, non-mapping
    slots skipped, unknown slots passed through (the spec build already
    rejects them for real charts). Every schema-legal value additionally
    interns into the snapshot; each value the schema refuses lands in
    `writer_domain` instead, so nothing declared is dropped in either
    direction and the not-yet-IR remainder is exactly enumerable.
    """
    from .._chromebox import expand_box_shorthands

    dom = spec.get("dom") or {}
    raw = dom.get("styles") or {}
    style = dom.get("style") or {}
    builder = SnapshotBuilder()
    view: dict[str, dict[str, Any]] = {}
    writer_domain: dict[str, dict[str, Any]] = {}
    environment = SnapshotEnvironment(
        width=_dimension(width, spec.get("width"), 800.0),
        height=_dimension(height, spec.get("height"), 500.0),
    )
    for slot, decls in raw.items():
        if not isinstance(decls, dict):
            continue
        view[str(slot)] = {_kebab(prop): value for prop, value in decls.items()}
    # Axis-chrome box slots intern one declaration and record N instances,
    # each with its qualifiers (axis id, major|minor, side, tick index) and
    # resolved geometry — produced by the writers' own box producer, so the
    # snapshot cannot disagree with what either writer draws.
    instance_records = _axis_instance_records(spec, view)
    for slot_name, normalized in view.items():
        if slot_name not in CHART_DOM_SLOTS:
            writer_domain[slot_name] = dict(normalized)
            continue
        legal: dict[str, Any] = {}
        residue: dict[str, Any] = {}
        # Schema v1 carries only longhands, so the box shorthands (`border`,
        # `padding`) intern expanded. The expansion is per shorthand and
        # all-or-nothing: if any expanded longhand is still writer-domain (an
        # em legend padding), the *authored* spelling lands in the residue —
        # the pinned residue enumeration stays in authored terms (§28).
        for name, value in normalized.items():
            expanded = {
                part: part_value
                for part, part_value in expand_box_shorthands({name: value}).items()
                # An explicit longhand beside the shorthand wins whatever the
                # authored order was; the shorthand fills only what is unsaid.
                if part == name or part not in normalized
            }
            try:
                resolved = {
                    part: assert_resolved(part, part_value) for part, part_value in expanded.items()
                }
            except ValueError:
                residue[name] = value
            else:
                legal.update(resolved)
        if legal:
            records = instance_records.get(slot_name)
            if records:
                # Per-instance records (axis families): real qualifiers and
                # layout geometry, one interned declaration for N instances.
                for qualifiers, geometry in records:
                    builder.add(slot_name, legal, qualifiers=qualifiers, geometry=geometry)
            else:
                # Otherwise the geometry the resolver can know without a
                # layout pass — the canvas rect for root/chrome, else None.
                builder.add(
                    slot_name, legal, geometry=_environment_geometry(slot_name, environment)
                )
        if residue:
            writer_domain[slot_name] = residue
    snapshot = builder.build(environment, tokens=_concrete_tokens(style))
    return DeclaredStyling(snapshot=snapshot, writer_domain=writer_domain, _view=view)


def _environment_geometry(
    slot: str, environment: SnapshotEnvironment
) -> Optional[tuple[float, float, float, float]]:
    """The slot geometry the declared resolver can know without a layout pass.

    `root` and `chrome` are the full canvas — (0, 0, width, height) in CSS px
    against the spec's own dimensions, never the host page's padding (the
    normalization rule for capture diffs: a browser capture must subtract host
    box offsets before comparing, plan §8 flag J). Slots whose box needs the
    layout pass (`title` wants measured text, `canvas` wants the plot rect)
    stay None here: the resolver cannot run `layout()` without re-entering
    itself through `slot_styles`, so their geometry is populated by the
    capture producers that already have the layout in hand.
    """
    if slot in ("root", "chrome"):
        return (0.0, 0.0, environment.width, environment.height)
    return None


def _dimension(override: Optional[float], declared: Any, fallback: float) -> float:
    for candidate in (override, declared):
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            value = float(candidate)
            if value > 0:
                return value
    return fallback


def _concrete_tokens(style: Any) -> dict[str, Any]:
    """The chart token bag, minus values the schema cannot carry yet.

    The bag is already renderer-neutral (every writer reads it), so almost
    everything passes; a var()-bearing token is browser-resolved chrome the
    declared resolver has no cascade for, and stays out of the snapshot the
    same way it stays out of a static file today.
    """
    from .resolved import assert_resolved_token

    if not isinstance(style, dict):
        return {}
    out: dict[str, Any] = {}
    for name, value in style.items():
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            continue
        try:
            out[str(name)] = assert_resolved_token(name, value)
        except ValueError:
            continue
    return out


__all__ = ["DeclaredStyling", "resolve_declared"]
