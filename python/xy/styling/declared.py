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

from dataclasses import dataclass, field
from typing import Any, Optional

from ..dom import CHART_DOM_SLOTS
from .resolved import ResolvedStyleSnapshot, SnapshotBuilder, SnapshotEnvironment, assert_resolved


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
        slot_name = str(slot)
        normalized = {_kebab(prop): value for prop, value in decls.items()}
        view[slot_name] = normalized
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
