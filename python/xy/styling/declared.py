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

The divergence between the two is presentational number formatting plus one
named residue (§28, recorded not smuggled): the legend's geometry runs in em
multipliers (`_svg._legend_em` — `padding`/`row-gap`/`font-size` em strings
are the legend's own unit domain, not CSS lengths to pre-resolve), and
schema v1 rightly refuses relative units, so those values appear in
`writer_domain` and the view but not the snapshot. The chrome-parity phase
moves legend geometry to resolved px and retires both divergences;
`tests/test_declared_snapshot.py` pins the view equivalence and enumerates
the residue until then.
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
    dom = spec.get("dom") or {}
    raw = dom.get("styles") or {}
    style = dom.get("style") or {}
    builder = SnapshotBuilder()
    view: dict[str, dict[str, Any]] = {}
    writer_domain: dict[str, dict[str, Any]] = {}
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
        for name, value in normalized.items():
            try:
                assert_resolved(name, value)
            except ValueError:
                residue[name] = value
            else:
                legal[name] = value
        if legal:
            records = instance_records.get(slot_name)
            if records:
                for qualifiers, geometry in records:
                    builder.add(slot_name, legal, qualifiers=qualifiers, geometry=geometry)
            else:
                builder.add(slot_name, legal)
        if residue:
            writer_domain[slot_name] = residue
    environment = SnapshotEnvironment(
        width=_dimension(width, spec.get("width"), 800.0),
        height=_dimension(height, spec.get("height"), 500.0),
    )
    snapshot = builder.build(environment, tokens=_concrete_tokens(style))
    return DeclaredStyling(snapshot=snapshot, writer_domain=writer_domain, _view=view)


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
