"""Report-only export preflight: what survives an export, and what does not.

`chart.style_compatibility_report(target=...)` answers `spec/api/export.md` §9
programmatically, per chart, before any bytes exist: for the requested target
and engine it lists which styling sources are present, how each styled slot
routes, and exactly which declarations would not survive. Nothing here changes
export behavior — the staged `compatibility=` modes that act on this report
land separately, so this module can be trusted from any code path.

Three rules keep the report honest:

1. **No silent decisions (§28).** Every declared style ends in exactly one
   route: it survives, it is state-gated chrome a clean static file does not
   contain, or it is named as a loss. There is no fourth, quiet bucket.
2. **Constant time when there is nothing to route.** A chart with no
   `class_names`, no per-slot `styles`, and no `custom_css` short-circuits to
   a lossless report without walking any slot — the preflight is free exactly
   where exports are hot.
3. **One source of truth per fact.** Slot routing derives from the capability
   registry, the honored property subsets from `xy._svg` (which the writers
   themselves read), and engine selection from `xy.export`'s own resolver.
   This module restates none of them, so it cannot disagree with them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from ..dom import validate_dom_slots
from . import capabilities

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, typing only
    from .._figure import Figure

#: Routes a declared style can take. Stable strings: the staged
#: `compatibility=` modes and the tests key on them.
ROUTE_SURVIVES = "survives"
ROUTE_SUBSET = "native-subset"
ROUTE_BROWSER_ONLY = "browser-only"
ROUTE_STATE_GATED = "state-gated"

#: The staged compatibility modes, in rollout order. `legacy` is today's
#: behavior and the default; `warn` surfaces every loss as one
#: `StyleCompatibilityWarning`; `strict` refuses to emit bytes that drop a
#: declaration. "lossless" is reserved for the phase that lets `Engine.auto`
#: re-route on preflight evidence — accepting it before that phase would make
#: the name a lie, so it is rejected now. The default flips on the schedule in
#: `spec/process/style-compatibility-migration.md`, never silently.
COMPATIBILITY_MODES: tuple[str, ...] = ("legacy", "warn", "strict")


class StyleCompatibilityWarning(UserWarning):
    """An export in `compatibility="warn"` mode dropped declared styling."""


class StyleCompatibilityError(ValueError):
    """An export in `compatibility="strict"` mode refused to drop styling.

    Carries the full preflight `report`; the message is its `explain()` plus
    the ways out, so the fix is in the traceback rather than a docs hunt.
    """

    def __init__(self, message: str, report: StyleCompatibilityReport) -> None:
        super().__init__(message)
        self.report = report


_RASTER_FORMATS = frozenset({"png", "jpeg", "webp"})
_VECTOR_FORMATS = frozenset({"svg", "pdf"})

_SLOTS_BY_ID = {slot.id: slot for slot in capabilities.CHART_SLOTS}


@dataclass(frozen=True)
class SlotFinding:
    """How one styled slot routes for the requested target."""

    slot: str
    source: str  # "styles" | "class_names"
    applicability: str  # "static" or the gating export state
    route: str  # one of the ROUTE_* strings
    kept: tuple[str, ...] = ()
    lost: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class StyleCompatibilityReport:
    """The preflight answer for one chart and one export target.

    `lossless` is the single bit the staged modes will act on: True means the
    export preserves every declared style that the target's document can
    contain (state-gated chrome is recorded, not counted — a clean static
    file has no tooltip to style). `error` carries the message of an export
    that would refuse outright (for example `custom_css` with a pinned native
    engine), mirroring the export path's own exception rather than predicting
    a different outcome.
    """

    target: str
    engine: str
    sources: dict[str, bool] = field(default_factory=dict)
    findings: tuple[SlotFinding, ...] = ()
    losses: tuple[str, ...] = ()
    lossless: bool = True
    error: Optional[str] = None

    def explain(self) -> str:
        """The report as readable lines, one decision each."""
        head = f"style compatibility for {self.target} via {self.engine} engine"
        lines = [head]
        present = [name for name, on in self.sources.items() if on] or ["(defaults only)"]
        lines.append("sources: " + ", ".join(present))
        if self.error is not None:
            lines.append(f"refused: {self.error}")
            return "\n".join(lines)
        for finding in self.findings:
            bits = [f"{finding.source}[{finding.slot!r}]: {finding.route}"]
            if finding.lost:
                bits.append("loses " + ", ".join(finding.lost))
            if finding.detail:
                bits.append(finding.detail)
            lines.append("  " + " — ".join(bits))
        lines.append("lossless" if self.lossless else f"{len(self.losses)} loss(es)")
        return "\n".join(lines)


def _sources(figure: Figure, custom_css: Optional[str]) -> dict[str, bool]:
    """Which styling sources this chart carries. Attribute checks only."""
    return {
        "chart_style": bool(figure.style),
        "slot_styles": bool(figure.chrome_styles),
        "class_names": bool(figure.class_names),
        "custom_css": custom_css is not None,
    }


def _resolve(target: str, engine: object, custom_css: Optional[str]) -> tuple[str, str, str]:
    """(format, engine, error) via the export module's own resolver.

    Deferred import: `export` pulls in the browser-discovery machinery, and
    `capabilities` must stay importable from the docs generator without it.

    Browser-resolved targets validate `custom_css` through the export path's
    own `_custom_css_block` — the same type check and `</style>`/`<!--`
    rejection the standalone document performs — in the same order the export
    performs them (engine resolution first). A report may not say "lossless"
    about an export that would refuse the stylesheet.
    """
    from .. import export

    fmt = export._normalize_format(target, allow_html=True)
    if fmt == "html":
        resolved = "browser"
    else:
        try:
            resolved = export._resolve_image_engine(engine, fmt, custom_css)
        except ValueError as exc:
            return fmt, "unresolved", str(exc)
    if resolved == "browser" and custom_css is not None:
        try:
            export._custom_css_block(custom_css)
        except (TypeError, ValueError) as exc:
            return fmt, resolved, str(exc)
    return fmt, resolved, ""


def _slot_family(fmt: str) -> str:
    """The writer family a format belongs to, refusing formats outside both.

    Membership is explicit on both sides so a format added later to
    `export._normalize_format` cannot silently be reported against the vector
    subset — it fails here until someone classifies it.
    """
    if fmt in _RASTER_FORMATS:
        return "native_raster"
    if fmt in _VECTOR_FORMATS:
        return "native_vector"
    raise ValueError(f"preflight has no writer family for format {fmt!r}")


def _honored_props(slot: str, family: str) -> tuple[frozenset[str], str]:
    """(honored property names, qualifier) for a native-subset slot.

    The subsets are the writers' own constants. `legend` honors box properties
    beyond the shared text subset through its merged-declaration channel; that
    set lives in the writer's merge logic rather than a constant yet, so the
    report stays at declaration granularity there instead of guessing — the
    qualifier says so, and the shared IR change makes it exact.
    """
    from .. import _svg

    text = frozenset(_svg.SLOT_RASTER_PROPS if family == "native_raster" else _svg.SLOT_TEXT_PROPS)
    if slot == "legend":
        return text, (
            "box properties (background, shadow, radius, padding) route through the "
            "merged legend declaration; see the capability matrix legend note"
        )
    return text, ""


def _css_prop(name: str) -> str:
    """Match the writers' spelling: kebab-case, custom properties untouched."""
    text = str(name)
    return text if text.startswith("--") else text.replace("_", "-")


def _class_finding(slot: str, fmt: str) -> SlotFinding:
    meta = _SLOTS_BY_ID[slot]
    if meta.applicability != "static":
        return SlotFinding(
            slot=slot,
            source="class_names",
            applicability=meta.applicability,
            route=ROUTE_STATE_GATED,
            detail=(
                f"{meta.applicability}-state chrome; a clean static {fmt} does not "
                "contain it, so nothing in the file is unstyled"
            ),
        )
    return SlotFinding(
        slot=slot,
        source="class_names",
        applicability="static",
        route=ROUTE_BROWSER_ONLY,
        lost=("*",),
        detail=(
            "a class selects a rule out of a stylesheet, and a native export has no "
            "stylesheet — browser and Chromium targets honor it"
        ),
    )


def _styles_finding(slot: str, decls: dict[str, Any], fmt: str) -> SlotFinding:
    meta = _SLOTS_BY_ID[slot]
    family = _slot_family(fmt)
    props = tuple(_css_prop(name) for name in decls)
    if meta.applicability != "static":
        return SlotFinding(
            slot=slot,
            source="styles",
            applicability=meta.applicability,
            route=ROUTE_STATE_GATED,
            detail=(
                f"{meta.applicability}-state chrome; a clean static {fmt} does not "
                "contain it, so nothing in the file is unstyled"
            ),
        )
    if slot == "root" or meta.support[family] == "none":
        detail = meta.notes if slot == "root" else "no native path for this slot yet"
        return SlotFinding(
            slot=slot,
            source="styles",
            applicability="static",
            route=ROUTE_BROWSER_ONLY,
            lost=props,
            detail=detail,
        )
    honored, qualifier = _honored_props(slot, family)
    kept = tuple(p for p in props if p in honored)
    lost = tuple(p for p in props if p not in honored)
    if slot == "legend":
        # Declaration-level: unlisted properties may still route through the
        # merged legend channel, so they are qualified rather than declared
        # lost (§28: unsure is said out loud, not rounded either direction).
        return SlotFinding(
            slot=slot,
            source="styles",
            applicability="static",
            route=ROUTE_SUBSET,
            kept=kept,
            lost=(),
            detail=qualifier,
        )
    if lost:
        return SlotFinding(
            slot=slot,
            source="styles",
            applicability="static",
            route=ROUTE_SUBSET,
            kept=kept,
            lost=lost,
            detail="outside the writer's honored subset for this slot",
        )
    return SlotFinding(
        slot=slot,
        source="styles",
        applicability="static",
        route=ROUTE_SURVIVES,
        kept=kept,
    )


def route_resolved(
    figure: Figure,
    *,
    fmt: str,
    resolved_engine: str,
    custom_css: Optional[str] = None,
) -> StyleCompatibilityReport:
    """The routing core, for callers that already resolved format and engine.

    The export paths call this with their own resolution result so the
    resolver (and its deprecation warnings) runs exactly once per export;
    `preflight()` wraps it with a resolution of its own for standalone use.
    """
    sources = _sources(figure, custom_css)
    if resolved_engine == "browser":
        # The live client renders the full cascade; nothing can drop.
        return StyleCompatibilityReport(target=fmt, engine=resolved_engine, sources=sources)
    if not (figure.class_names or figure.chrome_styles):
        # The constant-time path: chart-level `style=` and mark/axis `style=`
        # are full in every renderer (see the capability matrix), so with no
        # class or per-slot declarations there is nothing that can drop.
        return StyleCompatibilityReport(target=fmt, engine=resolved_engine, sources=sources)

    # Mirror the spec build's own validation rather than skipping entries it
    # would refuse: `Figure.class_names`/`chrome_styles` are assignable, so a
    # report can be requested before `_dom_spec` validates them. A silently
    # omitted entry would be a report claiming exhaustiveness while hiding a
    # declaration — the exact §28 failure this module exists to end.
    validate_dom_slots(figure.class_names, "class_names")
    validate_dom_slots(figure.chrome_styles, "chrome_styles")
    findings: list[SlotFinding] = []
    for slot in figure.class_names:
        findings.append(_class_finding(slot, fmt))
    for slot, decls in figure.chrome_styles.items():
        if not isinstance(decls, dict):
            raise ValueError(
                f"chrome_styles[{slot!r}] must be a mapping of declarations, got {decls!r}"
            )
        findings.append(_styles_finding(slot, decls, fmt))

    losses = tuple(
        f"{finding.source}[{finding.slot!r}] -> {', '.join(finding.lost)}"
        for finding in findings
        if finding.lost
    )
    return StyleCompatibilityReport(
        target=fmt,
        engine=resolved_engine,
        sources=sources,
        findings=tuple(findings),
        losses=losses,
        lossless=not losses,
    )


def preflight(
    figure: Figure,
    *,
    target: str = "png",
    engine: object = None,
    custom_css: Optional[str] = None,
) -> StyleCompatibilityReport:
    """Route every declared style for one export target, without exporting.

    `engine` accepts the same values as the export APIs (`Engine`, its string
    aliases, or None for auto). The report mirrors the export path's actual
    behavior, including its refusals — it never predicts a different outcome
    than running the export would produce.
    """
    fmt, resolved, error = _resolve(target, engine, custom_css)
    if error:
        return StyleCompatibilityReport(
            target=fmt,
            engine=resolved,
            sources=_sources(figure, custom_css),
            lossless=False,
            losses=(error,),
            error=error,
        )
    return route_resolved(figure, fmt=fmt, resolved_engine=resolved, custom_css=custom_css)


def validate_compatibility(value: object) -> str:
    """The mode, or a loud error naming the vocabulary (and the reserved word)."""
    if isinstance(value, str) and value in COMPATIBILITY_MODES:
        return value
    if value == "lossless":
        raise ValueError(
            'compatibility="lossless" is reserved for the lossless-routing phase '
            "(spec/process/style-compatibility-migration.md); until it can re-route "
            f"engines on preflight evidence, pick one of {COMPATIBILITY_MODES}"
        )
    raise ValueError(f"compatibility must be one of {COMPATIBILITY_MODES}, got {value!r}")


def enforce(
    figure: Figure,
    *,
    fmt: str,
    resolved_engine: str,
    custom_css: Optional[str],
    compatibility: str,
) -> None:
    """Apply a compatibility mode to one already-resolved export.

    `legacy` returns before doing anything at all — the default path pays
    zero. `warn` and `strict` pay the preflight only when the chart carries
    class or per-slot declarations and the engine is native; a lossless
    report also returns quietly. Engines are never re-routed here: the mode
    decides whether to proceed, warn, or refuse — never where to render
    (spec/process/style-compatibility-migration.md pins that contract).
    """
    import warnings

    mode = validate_compatibility(compatibility)
    if mode == "legacy":
        return
    if resolved_engine == "browser" or not (figure.class_names or figure.chrome_styles):
        return
    report = route_resolved(figure, fmt=fmt, resolved_engine=resolved_engine, custom_css=custom_css)
    if report.lossless:
        return
    # SVG is native-only (a browser screenshot cannot emit vector SVG), so
    # recommending engine=Engine.chromium there would recommend a refusal.
    keeps = (
        "to_html() keeps everything (SVG is native-only, so Engine.chromium "
        "is not a route for this format)"
        if fmt == "svg"
        else "engine=Engine.chromium or to_html() keeps everything"
    )
    if mode == "warn":
        warnings.warn(
            StyleCompatibilityWarning(
                f"this {fmt} export drops declared styling — "
                + "; ".join(report.losses)
                + " — chart.style_compatibility_report() has the full routing; "
                + keeps
            ),
            stacklevel=_caller_stacklevel(),
        )
        return
    raise StyleCompatibilityError(
        report.explain()
        + "\nstrict compatibility refuses to drop declared styling; "
        + keeps
        + ", or move it into chart/mark style= or a supported styles= subset, "
        'or export with compatibility="warn" during migration',
        report,
    )


def _caller_stacklevel() -> int:
    """The stacklevel that lands the warning on the caller's export line.

    The distance from `enforce` to user code varies by entry point (module
    function, Figure method, Chart method, batch plan), so it is measured:
    walk outward from `enforce` until the first frame outside the xy
    package. Counted so `warnings.warn(..., stacklevel=n)` inside `enforce`
    attributes the warning to that frame.
    """
    import sys
    from pathlib import Path

    package_dir = str(Path(__file__).resolve().parents[1])
    frame = sys._getframe(1)  # enforce's frame
    level = 1
    while frame.f_back is not None and str(Path(frame.f_code.co_filename).resolve()).startswith(
        package_dir
    ):
        frame = frame.f_back
        level += 1
    return level


__all__ = [
    "COMPATIBILITY_MODES",
    "ROUTE_BROWSER_ONLY",
    "ROUTE_STATE_GATED",
    "ROUTE_SUBSET",
    "ROUTE_SURVIVES",
    "SlotFinding",
    "StyleCompatibilityError",
    "StyleCompatibilityReport",
    "StyleCompatibilityWarning",
    "enforce",
    "preflight",
    "route_resolved",
    "validate_compatibility",
]
