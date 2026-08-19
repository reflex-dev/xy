"""Chart plans: validated, data-free chart structure for the data-bound tier.

A plan is the server-side half of the composite figure identity
``xyp1|<digest>|<data token>`` (spec/design/reflex-integration.md): the xy
node tree with **string channels only**, compiled once at page evaluation.

- **Build** (factory call = page evaluation = Reflex compile): construct the
  real xy tree, bind a **zero-row** placeholder column for every referenced
  channel name, and call ``.figure()`` once under the core's
  ``structural_probe()`` mode — the mark/config validation gate (facts
  X1/X2, pinned in tests/test_validation_timing.py) runs in milliseconds
  with no real data and **no invented data**: in probe mode a mark whose
  channels are all empty validates its configuration (enums, bounds,
  colormaps, range shapes) and skips data-dependent work, so a probe failure always
  indicts the chart's structure, and no value-dependent check (hexbin
  range/mincnt filtering, contour marching, quantiles) can fire on
  placeholder values or allocate at page evaluation. Real-data shape
  contracts (coupled lengths, z's 2-D-ness) stay at bind. The probe figure
  is discarded; what is kept is the digest, the recorded column names, and
  (for live charts) the probe's Tailwind class inventory.
- **Serialize**: nodes → canonical JSON (sorted keys, ``plan_version``) →
  sha256 prefix = ``digest``. The digest is a *content address*: every
  worker that evaluates the page derives the same digest and holds the plan
  in this process-local map — and backend-only workers, which skip the
  frontend compile, get the same evaluation from ``setup(app)``'s startup
  lifespan (app.py `_ensure_page_plans`). A lookup miss is hot-reload
  drift and answers ``err {resync}`` naming the digest.
- **Bind** (serve time): columns + plan → a **fresh** ``Chart`` (never
  reuse — ``Chart.figure()`` memoizes, X3) → ``Figure``. Column mismatches
  raise :class:`PlanBindError` naming both sides.

Plans hold no data and no session identity; they are pure functions of page
source. Everything session-shaped lives in the data token half.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib
import json
import sys
import types
from collections.abc import Mapping
from typing import Any, Optional

import numpy as np

from xy.components import Chart, Component, Mark, structural_probe

__all__ = [
    "PLAN_VERSION",
    "ChartPlan",
    "PlanBindError",
    "PlanError",
    "PlanMissError",
    "build_plan",
    "plan_of",
    "register_plan",
]

PLAN_VERSION = 1
_DIGEST_CHARS = 20  # sha256 hex prefix; content address for a process-local map


class PlanError(ValueError):
    """A chart plan could not be built, resolved, or bound."""


class PlanMissError(PlanError):
    """No plan registered under a digest (hot-reload drift — client resyncs)."""

    def __init__(self, digest: str) -> None:
        super().__init__(
            f"unknown chart plan {digest!r} on this worker (stale page after a "
            "hot reload?); re-subscribe against the recompiled page"
        )
        self.digest = digest


class PlanBindError(PlanError):
    """The data var's columns do not satisfy the plan's bindings."""


class _ProbeTable(Mapping):
    """Zero-row placeholder table that records every column it resolves.

    ``Chart.figure()`` resolves string channels through ``data[name]``
    (the exact production code path), so the recorded names are *derived*
    from the real resolution logic — the plan's column list can never drift
    from what binding will actually look up. Every column is empty: under
    ``structural_probe()`` the marks validate configuration against empty
    channels and never aggregate, so no synthetic values exist for a
    validator to (falsely) accept or reject.
    """

    def __init__(self) -> None:
        self.seen: list[str] = []

    def __getitem__(self, key: str) -> np.ndarray:
        if key not in self.seen:
            self.seen.append(key)
        return np.empty(0, dtype=np.float64)

    def __iter__(self):  # pragma: no cover - Mapping protocol completeness
        return iter(self.seen)

    def __len__(self) -> int:  # pragma: no cover - Mapping protocol completeness
        return len(self.seen)


def _code_fingerprint(fn: Any) -> str:
    """Content hash of a pure-Python function's behavior.

    A qualified name is *identity*, not *content*: hashing only the import
    path would keep the digest stable while the function body changes (a
    rolling deployment then executes two behaviors behind one address). The
    fingerprint covers the bytecode, referenced names, nested code objects,
    and default values. It is deterministic across processes for one
    interpreter version; across differing interpreter versions digests
    diverge and stale clients resync — fail-safe, never silently wrong.
    """
    h = hashlib.sha256()

    def feed(code: types.CodeType) -> None:
        h.update(code.co_code)
        h.update(",".join(code.co_names).encode())
        h.update(",".join(code.co_varnames).encode())
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                feed(const)
            elif isinstance(const, frozenset):
                # frozenset repr order follows per-process string hashing;
                # sort for a process-independent byte stream.
                h.update(",".join(sorted(map(repr, const))).encode())
            else:
                h.update(repr(const).encode())

    feed(fn.__code__)
    h.update(repr(getattr(fn, "__defaults__", None)).encode())
    h.update(repr(getattr(fn, "__kwdefaults__", None)).encode())
    return h.hexdigest()[:16]


def _resolve_qualname(module: str, qualname: str) -> Any:
    """The object ``module.qualname`` names right now, or None."""
    try:
        target: Any = importlib.import_module(module)
        for part in qualname.split("."):
            target = getattr(target, part)
    except Exception:  # noqa: BLE001 - resolution failure means "not addressable"
        return None
    return target


def _callable_address(value: Any, context: str) -> dict[str, str]:
    """Serialize one plan callable as a true content address (fail closed).

    Bound methods are refused outright: the instance state behind
    ``__self__`` has no content address, so two differently configured
    instances would collide on one digest and last-write-wins registration
    would silently swap behavior. Pure-Python functions carry a code
    fingerprint beside their import path; C-level callables (ufuncs,
    builtins) must resolve back to the same object by name and carry their
    distribution's version, which is what pins their behavior.
    """
    if getattr(value, "__self__", None) is not None:
        raise PlanError(
            f"{context} holds a bound method ({value!r}). The instance state "
            "behind it has no content address, so differently configured "
            "instances would collide on one plan digest. Use a module-level "
            "function, or build the chart with @reflex_xy.figure."
        )
    module = getattr(value, "__module__", "") or ""
    qualname = getattr(value, "__qualname__", "") or ""
    if not module or not qualname or "<" in module or "<" in qualname:
        raise PlanError(
            f"{context} holds a {type(value).__name__} without a stable "
            "qualified name (a lambda, closure, or partial?), which cannot "
            "be content-addressed into a chart plan. Use a module-level "
            "function, or build the chart with @reflex_xy.figure."
        )
    code = getattr(value, "__code__", None)
    if code is not None:
        if code.co_freevars:
            raise PlanError(
                f"{context} holds a closure ({module}.{qualname}), whose "
                "captured variables have no content address. Use a module-"
                "level function, or build the chart with @reflex_xy.figure."
            )
        return {"~callable": f"{module}.{qualname}", "code": _code_fingerprint(value)}
    if _resolve_qualname(module, qualname) is not value:
        raise PlanError(
            f"{context} holds {value!r}, whose qualified name "
            f"{module}.{qualname!r} does not resolve back to it — the name "
            "cannot address this callable across workers. Use a module-level "
            "function, or build the chart with @reflex_xy.figure."
        )
    root = sys.modules.get(module.split(".", 1)[0])
    return {"~callable": f"{module}.{qualname}", "dist": str(getattr(root, "__version__", ""))}


def _plain(value: Any, context: str) -> Any:
    """Canonical JSON-able copy of one plan node field (fail closed)."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        node: dict[str, Any] = {"~node": type(value).__name__}
        for field in dataclasses.fields(value):
            node[field.name] = _plain(getattr(value, field.name), f"{context}.{field.name}")
        return node
    if isinstance(value, Mapping):
        return {str(key): _plain(item, f"{context}.{key}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item, context) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if callable(value):
        return _callable_address(value, context)
    raise PlanError(
        f"{context} holds a {type(value).__name__}, which cannot be part of a "
        "data-bound chart plan. Plans are data-free structure: bind columns "
        "by name (strings) and keep arrays in the @reflex_xy.data method; "
        "components (e.g. legend/tooltip render=) belong to the escape "
        "hatch (@reflex_xy.figure) or the static tier."
    )


@dataclasses.dataclass(frozen=True)
class ChartPlan:
    """One validated, data-free chart structure, addressed by content."""

    kind: str
    children: tuple[Component, ...]
    chart_props: dict[str, Any]
    columns: tuple[str, ...]  # channel names the probe resolved, in order
    tailwind_classes: str  # probe figure's DOM class inventory (live-tier scan)
    digest: str

    def chart(self, data: Any) -> Chart:
        """A fresh ``Chart`` over ``data`` (X3: never reuse a compiled one)."""
        return Chart(self.kind, self.children, data=data, **self.chart_props)

    def bind(self, columns: Mapping[str, Any], *, source: str = "the data var") -> Chart:
        """Bind real columns; missing bindings name both sides."""
        missing = [name for name in self.columns if name not in columns]
        if missing:
            bound = ", ".join(repr(name) for name in missing)
            produced = ", ".join(sorted(str(key) for key in columns)) or "no columns"
            noun = "columns" if len(missing) > 1 else "column"
            raise PlanBindError(f"plan binds {noun} {bound}; {source} produced {{{produced}}}")
        return self.chart(columns)


def build_plan(
    kind: str, children: tuple[Component, ...], chart_props: dict[str, Any]
) -> ChartPlan:
    """Compile + validate a plan and register it in this worker's map."""
    for child in children:
        if isinstance(child, Mark) and child.data is not None:
            raise PlanError(
                "per-mark data= is not supported in data-bound charts; bind one "
                "chart-level data source (this is tracked as deferred work in "
                "spec/design/reflex-component-api-implementation.md)"
            )
    # The plan must be immutable once addressed: hash a deep snapshot and
    # register *that* snapshot, so mutating a reused mark node or a props
    # dict after the factory call can never change binding behavior behind
    # an unchanged digest/columns record.
    children = copy.deepcopy(children)
    chart_props = copy.deepcopy(chart_props)
    serialized = {
        "plan_version": PLAN_VERSION,
        "kind": kind,
        "chart": {key: _plain(value, f"{kind}() {key}") for key, value in chart_props.items()},
        "children": [_plain(child, f"{kind}() child {i}") for i, child in enumerate(children)],
    }
    canonical = json.dumps(serialized, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:_DIGEST_CHARS]

    # The compile-time validation gate: bind zero-row placeholders for every
    # string channel and compile once under the core's structural-probe
    # mode — configuration validates, data-dependent work never runs on invented
    # values. Errors surface here — at page evaluation — with the ordinary
    # xy messages.
    probe = _ProbeTable()
    with structural_probe():
        probe_figure = Chart(kind, children, data=probe, **chart_props).figure()
    tailwind_classes = " ".join(probe_figure.dom_class_strings())

    plan = ChartPlan(
        kind=kind,
        children=children,
        chart_props=chart_props,
        columns=tuple(probe.seen),
        tailwind_classes=tailwind_classes,
        digest=digest,
    )
    return register_plan(plan)


#: Process-local {digest: plan}, populated wherever page bodies evaluate:
#: the frontend compile, and — for backend-only workers that skip it — the
#: setup(app) startup lifespan (app.py `_ensure_page_plans`). Entries are
#: tiny (node dataclasses with string channels) and bounded by page code.
_PLANS: dict[str, ChartPlan] = {}


def register_plan(plan: ChartPlan) -> ChartPlan:
    """Register a plan under its digest; returns the registered one.

    Last write wins (idempotent for identical content — the digest is the
    content address): after a hot reload re-evaluates the page, the fresh
    node objects replace the stale ones. An edited pure-Python callable
    changes the digest itself (its code fingerprint is part of the
    serialization), so behavior can never swap silently behind a stable
    address; C-level callables are pinned by import path + distribution
    version instead.
    """
    _PLANS[plan.digest] = plan
    return plan


def plan_of(digest: str) -> Optional[ChartPlan]:
    return _PLANS.get(digest)


def require_plan(digest: str) -> ChartPlan:
    plan = _PLANS.get(digest)
    if plan is None:
        raise PlanMissError(digest)
    return plan


def reset_plans_for_tests() -> None:
    """Forget every registered plan (test isolation only)."""
    _PLANS.clear()
