"""The `ResolvedStyleSnapshot`: one interned styling IR between every source
and every renderer.

Authored styling arrives from five mechanisms and two resolvers (the Python
style compiler today, the browser's computed-style capture next); renderers
should consume exactly one shape regardless of where it came from. That shape
is this module: **concrete values only** — a resolved color, a pixel length,
a settled font descriptor — never a `var()`, a `calc()`, an `em`, or anything
else whose meaning depends on a document the renderer does not have. A value
that still needs resolving is rejected loudly at construction (§28), because
a snapshot that smuggles one unresolved value re-creates in the IR the exact
per-renderer divergence the IR exists to end.

Declarations are **interned**: a snapshot stores each distinct declaration
once and instances reference it by index, so four hundred tick labels styled
alike cost one declaration plus four hundred three-item instances — the
size/capture budgets in the spec assume this, and
`tests/test_resolved_style_snapshot.py` enforces it with a dense-axis
fixture.

The schema is versioned independently of the wire protocol
(`STYLE_SNAPSHOT_VERSION`): nothing here rides the wire yet, so
`PROTOCOL_VERSION` does not bump — the capture/transport change bumps it,
carrying this schema as its payload (`spec/design/wire-protocol.md` §8).
`scripts/gen_style_snapshot_types.py` renders the TypeScript mirror from
this module, and the test suite fails when the two drift.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Optional

from ..dom import CHART_DOM_SLOTS

#: Bumped when the schema's shape or vocabulary changes. A consumer that sees
#: a version it does not know must refuse, not guess.
STYLE_SNAPSHOT_VERSION = 1

#: The closed property vocabulary of schema v1, grouped the way the renderers
#: consume it. Growing this list IS a schema change: add the property AND
#: bump `STYLE_SNAPSHOT_VERSION`, so a snapshot's vocabulary is always
#: recoverable from its version field alone. Names are kebab-case CSS except
#: the `xy-` prefixed ones, which have no CSS spelling (rotation).
PAINT_PROPERTIES_V1: tuple[str, ...] = (
    "color",
    "fill",
    "background",
    "background-image",
    "opacity",
    "fill-opacity",
    "stroke",
    "stroke-opacity",
    "stroke-width",
    "border-color",
    "border-style",
    "border-width",
    "border-radius",
    "box-shadow",
)

TYPOGRAPHY_PROPERTIES_V1: tuple[str, ...] = (
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "letter-spacing",
    "line-height",
    "text-align",
    "xy-rotation",
)

LAYOUT_PROPERTIES_V1: tuple[str, ...] = (
    "padding-top",
    "padding-right",
    "padding-bottom",
    "padding-left",
    "gap",
    "width",
    "height",
    "max-width",
    "max-height",
    "transform",
    "clip-path",
)

EFFECT_PROPERTIES_V1: tuple[str, ...] = (
    "filter",
    "mix-blend-mode",
    "isolation",
    "mask",
)

PROPERTIES_V1: tuple[str, ...] = (
    PAINT_PROPERTIES_V1 + TYPOGRAPHY_PROPERTIES_V1 + LAYOUT_PROPERTIES_V1 + EFFECT_PROPERTIES_V1
)

_PROPERTY_SET = frozenset(PROPERTIES_V1)

#: Constructs whose value depends on a document, a cascade, or an
#: environment the renderer does not have. Their presence means the value is
#: not resolved, whatever else it looks like.
_UNRESOLVED_MARKERS: tuple[str, ...] = ("var(", "calc(", "env(", "attr(", "inherit", "unset")

#: Length units a *resolved* value may not carry: every one is relative to
#: font metrics or viewport the consumer would have to re-derive. Resolved
#: lengths are plain numbers (CSS px).
_RELATIVE_UNITS: tuple[str, ...] = ("em", "rem", "ex", "ch", "vw", "vh", "vmin", "vmax", "%")

_COLOR_SCHEMES = frozenset({"light", "dark"})


def assert_resolved(prop: str, value: object) -> str | float:
    """A schema-v1 value, or a loud error saying exactly why it is not one.

    Numbers pass as finite floats. Strings pass unless they carry an
    unresolved construct or end in a relative unit — the two ways a value can
    quietly mean something different in the consumer than it did in the
    source. There is no silent coercion in either direction.
    """
    if prop not in _PROPERTY_SET:
        raise ValueError(
            f"{prop!r} is not in the schema-v{STYLE_SNAPSHOT_VERSION} vocabulary; "
            "growing the vocabulary is a schema change (bump STYLE_SNAPSHOT_VERSION)"
        )
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{prop}: resolved values are numbers or strings, got {value!r}")
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{prop}: resolved numbers must be finite, got {value!r}")
        return number
    text = value.strip()
    if not text:
        raise ValueError(f"{prop}: a resolved value cannot be empty")
    lowered = text.lower()
    for marker in _UNRESOLVED_MARKERS:
        if marker in lowered:
            raise ValueError(
                f"{prop}: {text!r} still depends on a cascade the renderer does not "
                f"have ({marker.rstrip('(')}); resolve it before it enters the snapshot"
            )
    for unit in _RELATIVE_UNITS:
        if (
            lowered.endswith(unit)
            and lowered[: -len(unit)].replace(".", "", 1).lstrip("+-").isdigit()
        ):
            raise ValueError(
                f"{prop}: {text!r} is relative to metrics the consumer would have to "
                "re-derive; resolved lengths are plain numbers in CSS px"
            )
    return text


@dataclass(frozen=True)
class SlotInstance:
    """One styled occurrence of a slot, referencing an interned declaration.

    `qualifiers` is the stable identity beyond the slot name — for example
    `("y", "major", "3")` for a tick label — so repeated chrome keeps
    per-instance identity while sharing one declaration. `geometry` is the
    resolved box in CSS px `(x, y, w, h)` when the producer knows it;
    `content` is the drawn text when the slot has any.
    """

    slot: str
    declaration: int
    qualifiers: tuple[str, ...] = ()
    geometry: Optional[tuple[float, float, float, float]] = None
    content: Optional[str] = None


@dataclass(frozen=True)
class SnapshotEnvironment:
    """What the values were resolved against; part of every cache key."""

    width: float
    height: float
    dpr: float = 1.0
    color_scheme: str = "light"


@dataclass(frozen=True)
class ResolvedStyleSnapshot:
    """A complete, renderer-neutral styling result for one chart state."""

    environment: SnapshotEnvironment
    declarations: tuple[dict[str, str | float], ...] = ()
    instances: tuple[SlotInstance, ...] = ()
    tokens: dict[str, str | float] = field(default_factory=dict)
    states: tuple[str, ...] = ()
    unrepresentable: tuple[str, ...] = ()
    style_epoch: int = 0
    version: int = STYLE_SNAPSHOT_VERSION

    def to_payload(self) -> dict[str, Any]:
        """The JSON-safe wire shape (`spec/design/wire-protocol.md` §8).

        Snapshot-level keys are spelled out; the per-instance keys are the
        one-letter spellings the spec documents, because instances are the
        part that repeats with chart density.
        """
        return {
            "version": self.version,
            "style_epoch": self.style_epoch,
            "environment": {
                "width": self.environment.width,
                "height": self.environment.height,
                "dpr": self.environment.dpr,
                "color_scheme": self.environment.color_scheme,
            },
            "tokens": dict(self.tokens),
            "states": list(self.states),
            "unrepresentable": list(self.unrepresentable),
            "declarations": [dict(decl) for decl in self.declarations],
            "instances": [
                {
                    "s": inst.slot,
                    "d": inst.declaration,
                    **({"q": list(inst.qualifiers)} if inst.qualifiers else {}),
                    **({"g": list(inst.geometry)} if inst.geometry is not None else {}),
                    **({"c": inst.content} if inst.content is not None else {}),
                }
                for inst in self.instances
            ],
        }

    def payload_bytes(self) -> int:
        """Uncompressed serialized size — what the spec's 50 KB budget meters."""
        return len(json.dumps(self.to_payload(), separators=(",", ":")).encode("utf-8"))


class SnapshotBuilder:
    """Interning constructor: identical declarations share one record.

    The producer calls `add(slot, declaration, ...)` per styled instance and
    `build(...)` once; canonicalization (sorted property order) makes
    interning independent of declaration insertion order, so a builder fed
    the same styling in any order emits the same snapshot.
    """

    def __init__(self) -> None:
        self._declarations: list[dict[str, str | float]] = []
        self._index: dict[tuple[tuple[str, str | float], ...], int] = {}
        self._instances: list[SlotInstance] = []

    def intern(self, declaration: Mapping[str, object]) -> int:
        """The index for this declaration, adding it only if it is new."""
        if not declaration:
            raise ValueError("an empty declaration styles nothing; do not intern it")
        resolved = {prop: assert_resolved(prop, value) for prop, value in declaration.items()}
        key = tuple(sorted(resolved.items()))
        found = self._index.get(key)
        if found is not None:
            return found
        self._index[key] = len(self._declarations)
        self._declarations.append(dict(sorted(resolved.items())))
        return self._index[key]

    def add(
        self,
        slot: str,
        declaration: Mapping[str, object],
        *,
        qualifiers: Sequence[str] = (),
        geometry: Optional[Sequence[float]] = None,
        content: Optional[str] = None,
    ) -> int:
        """Record one styled slot instance; returns its declaration index."""
        if slot not in CHART_DOM_SLOTS:
            raise ValueError(f"unknown slot {slot!r}; expected one of CHART_DOM_SLOTS")
        geom: Optional[tuple[float, float, float, float]] = None
        if geometry is not None:
            values = tuple(float(v) for v in geometry)
            if len(values) != 4 or not all(math.isfinite(v) for v in values):
                raise ValueError(f"geometry must be four finite numbers (x, y, w, h): {geometry!r}")
            geom = values
        index = self.intern(declaration)
        self._instances.append(
            SlotInstance(
                slot=slot,
                declaration=index,
                qualifiers=tuple(str(q) for q in qualifiers),
                geometry=geom,
                content=content,
            )
        )
        return index

    def build(
        self,
        environment: SnapshotEnvironment,
        *,
        tokens: Optional[Mapping[str, object]] = None,
        states: Sequence[str] = (),
        unrepresentable: Sequence[str] = (),
        style_epoch: int = 0,
    ) -> ResolvedStyleSnapshot:
        if environment.color_scheme not in _COLOR_SCHEMES:
            raise ValueError(f"color_scheme must be one of {sorted(_COLOR_SCHEMES)}")
        resolved_tokens = {
            str(name): assert_resolved_token(name, value) for name, value in (tokens or {}).items()
        }
        return ResolvedStyleSnapshot(
            environment=environment,
            declarations=tuple(self._declarations),
            instances=tuple(self._instances),
            tokens=resolved_tokens,
            states=tuple(str(s) for s in states),
            unrepresentable=tuple(str(u) for u in unrepresentable),
            style_epoch=int(style_epoch),
        )


def assert_resolved_token(name: object, value: object) -> str | float:
    """Chart tokens carry open names but the same resolved-value contract."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"token {name!r}: resolved values are numbers or strings, got {value!r}")
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"token {name!r}: resolved numbers must be finite")
        return number
    lowered = value.lower()
    for marker in _UNRESOLVED_MARKERS:
        if marker in lowered:
            raise ValueError(
                f"token {name!r}: {value!r} still depends on a cascade "
                f"({marker.rstrip('(')}); resolve it before it enters the snapshot"
            )
    return value


def snapshot_from_payload(payload: Mapping[str, Any]) -> ResolvedStyleSnapshot:
    """The inverse of `to_payload`, refusing versions it does not know."""
    version = payload.get("version")
    if version != STYLE_SNAPSHOT_VERSION:
        raise ValueError(
            f"style snapshot version {version!r} is not supported "
            f"(this build reads v{STYLE_SNAPSHOT_VERSION}); refusing to guess"
        )
    env = payload["environment"]
    declarations = [
        {prop: assert_resolved(prop, value) for prop, value in decl.items()}
        for decl in payload.get("declarations", ())
    ]
    instances = []
    for raw in payload.get("instances", ()):
        index = raw["d"]
        if not isinstance(index, int) or not 0 <= index < len(declarations):
            raise ValueError(f"instance {raw!r} references declaration {index!r}, which is absent")
        geometry: Optional[tuple[float, float, float, float]] = None
        if "g" in raw:
            values = tuple(float(v) for v in raw["g"])
            if len(values) != 4 or not all(math.isfinite(v) for v in values):
                raise ValueError(f"instance {raw!r} geometry must be four finite numbers")
            geometry = values
        if raw["s"] not in CHART_DOM_SLOTS:
            raise ValueError(f"instance {raw!r} names unknown slot {raw['s']!r}")
        instances.append(
            SlotInstance(
                slot=raw["s"],
                declaration=index,
                qualifiers=tuple(str(q) for q in raw.get("q", ())),
                geometry=geometry,
                content=raw.get("c"),
            )
        )
    return ResolvedStyleSnapshot(
        environment=SnapshotEnvironment(
            width=float(env["width"]),
            height=float(env["height"]),
            dpr=float(env.get("dpr", 1.0)),
            color_scheme=str(env.get("color_scheme", "light")),
        ),
        declarations=tuple(dict(d) for d in declarations),
        instances=tuple(instances),
        tokens=dict(payload.get("tokens", {})),
        states=tuple(payload.get("states", ())),
        unrepresentable=tuple(payload.get("unrepresentable", ())),
        style_epoch=int(payload.get("style_epoch", 0)),
    )


__all__ = [
    "EFFECT_PROPERTIES_V1",
    "LAYOUT_PROPERTIES_V1",
    "PAINT_PROPERTIES_V1",
    "PROPERTIES_V1",
    "STYLE_SNAPSHOT_VERSION",
    "TYPOGRAPHY_PROPERTIES_V1",
    "ResolvedStyleSnapshot",
    "SlotInstance",
    "SnapshotBuilder",
    "SnapshotEnvironment",
    "assert_resolved",
    "assert_resolved_token",
    "snapshot_from_payload",
]
