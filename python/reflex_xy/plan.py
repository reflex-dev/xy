"""Chart plans: validated, data-free chart structure for the data-bound tier.

A plan is the server-side half of the composite figure identity
``xyp1|<digest>|<data token>`` (spec/design/reflex-integration.md): the xy
node tree with **string channels only**, compiled once at page evaluation.

- **Build** (factory call = page evaluation = Reflex compile): construct the
  real xy tree, bind a placeholder column for every referenced channel
  name, and call ``.figure()`` once — the full mark/config validation gate
  (facts X1/X2, pinned in tests/test_validation_timing.py) runs in
  milliseconds with no real data. Placeholders are zero-row except for the
  channels of the aggregating kinds (box, violin, hexbin, contour, heatmap,
  stairs, ecdf), whose validators need at least one finite value: those
  bind tiny fixed synthetic columns shaped per channel
  (:data:`_SYNTHETIC_CHANNELS`, the recorded table — spec:
  reflex-integration.md "Kind coverage"). The probe figure is discarded;
  what is kept is the digest, the recorded column names, and (for live
  charts) the probe's Tailwind class inventory.
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
import json
from collections.abc import Mapping
from typing import Any, Optional

import numpy as np

from xy.components import Chart, Component, Mark

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

#: Synthetic probe columns. Aggregating kinds (quantiles, bins, meshes)
#: refuse zero rows, so their channels probe with tiny *fixed* placeholder
#: arrays instead — deterministic constants that satisfy every value-domain
#: precondition a validator imposes (finite, positive, strictly increasing,
#: log-scale-safe), so a probe failure still means the *structure* is
#: invalid, never the made-up values. Real-data shape contracts (actual
#: lengths, the user's z being 2-D) stay where they always were: at bind.
_PROBE_LEN = 8
_PROBE_GRID_SIDE = 4


def _spread() -> np.ndarray:
    return np.linspace(1.0, float(_PROBE_LEN), _PROBE_LEN)


def _one_group() -> np.ndarray:
    return np.ones(_PROBE_LEN, dtype=np.float64)


def _grid() -> np.ndarray:
    side = _PROBE_GRID_SIDE
    return np.linspace(1.0, float(side * side), side * side).reshape(side, side)


def _grid_side() -> np.ndarray:
    return np.linspace(1.0, float(_PROBE_GRID_SIDE), _PROBE_GRID_SIDE)


def _bin_edges() -> np.ndarray:
    return np.linspace(1.0, float(_PROBE_LEN + 1), _PROBE_LEN + 1)


#: The recorded shape table: mark kind -> {channel storage: builder}. Keys
#: name where the factory stores each column-capable channel on the Mark
#: node — its ``x``/``y`` fields or a ``props`` entry (``box(values=...)``
#: lands on field ``x``; ``stairs(edges=...)`` on field ``y``;
#: ``heatmap(z=...)`` in ``props["z"]``). Kinds absent here probe zero-row.
#: Extending a kind means recording its minimal validator contract here —
#: never a silent guess (§28 spirit); pinned by tests/reflex_adapter/
#: test_plan.py and tests/test_validation_timing.py.
_SYNTHETIC_CHANNELS: dict[str, dict[str, Any]] = {
    "box": {"x": _spread, "props.x": _one_group, "props.group": _one_group},
    "violin": {"x": _spread, "props.x": _one_group, "props.group": _one_group},
    "hexbin": {"x": _spread, "y": _spread, "props.C": _spread},
    "contour": {"props.z": _grid, "x": _grid_side, "y": _grid_side},
    "heatmap": {"props.z": _grid, "x": _grid_side, "y": _grid_side},
    "stairs": {"x": _spread, "y": _bin_edges},
    "ecdf": {"x": _spread},
}


def _probe_shapes(children: tuple[Component, ...]) -> dict[str, np.ndarray]:
    """Synthetic columns for every aggregating-kind channel bound by name.

    Shared column names keep one shape (first mark wins) — the same column
    genuinely is the same array at bind time. A column shared between an
    aggregating channel and a zero-row mark's channel cannot probe (the
    lengths disagree); the probe then fails with xy's ordinary length
    message, which is also what real data would do in every case where the
    aggregating channel's shape truly differs.
    """
    shapes: dict[str, np.ndarray] = {}
    for child in children:
        if not isinstance(child, Mark):
            continue
        for location, build in _SYNTHETIC_CHANNELS.get(child.kind, {}).items():
            if location.startswith("props."):
                name = child.props.get(location[len("props.") :])
            else:
                name = getattr(child, location, None)
            if isinstance(name, str):
                shapes.setdefault(name, build())
    return shapes


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
    """Placeholder table that records every column it resolves.

    ``Chart.figure()`` resolves string channels through ``data[name]``
    (the exact production code path), so the recorded names are *derived*
    from the real resolution logic — the plan's column list can never drift
    from what binding will actually look up. Columns are zero-row unless
    ``shapes`` carries a synthetic array for the name (the aggregating
    kinds' channels, from :data:`_SYNTHETIC_CHANNELS`).
    """

    def __init__(self, shapes: Optional[Mapping[str, np.ndarray]] = None) -> None:
        self.seen: list[str] = []
        self._shapes = dict(shapes or {})

    def __getitem__(self, key: str) -> np.ndarray:
        if key not in self.seen:
            self.seen.append(key)
        shaped = self._shapes.get(key)
        if shaped is not None:
            return shaped
        return np.empty(0, dtype=np.float64)

    def __iter__(self):  # pragma: no cover - Mapping protocol completeness
        return iter(self.seen)

    def __len__(self) -> int:  # pragma: no cover - Mapping protocol completeness
        return len(self.seen)


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
        # A module-level named callable (hexbin's reduce_C_function is
        # np.mean by default) has a stable import path — that path is its
        # content address. Lambdas and closures don't, so they cannot keep
        # digests faithful and are refused like any other opaque value.
        module = getattr(value, "__module__", "") or ""
        qualname = getattr(value, "__qualname__", "") or ""
        if module and qualname and "<" not in module and "<" not in qualname:
            return {"~callable": f"{module}.{qualname}"}
        raise PlanError(
            f"{context} holds a {type(value).__name__} without a stable "
            "qualified name (a lambda or closure?), which cannot be "
            "content-addressed into a chart plan. Use a module-level "
            "function, or build the chart with @reflex_xy.figure."
        )
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

    # The compile-time validation gate: bind placeholders for every string
    # channel (zero-row, or the shaped synthetic columns for aggregating
    # kinds) and compile once. Errors surface here — at page evaluation —
    # with the ordinary xy messages.
    probe = _ProbeTable(_probe_shapes(children))
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
    node objects replace the stale ones, which matters for the one node
    field a digest addresses by *name* rather than by value (module-level
    callables, e.g. a hexbin ``reduce_C_function`` whose body was edited).
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
