"""Data-bound chart factories: the component-shaped `reflex_xy` chart API.

The flat, single-mark form (Level 1 of
spec/design/reflex-component-api-options.md §5.6)::

    reflex_xy.scatter_chart(
        data=Dash.cloud,                 # @reflex_xy.data var (columns only)
        x="x", y="y", color="mag",       # channels: column-name strings
        colormap="viridis",              # mark options, validated at compile
        x_axis=reflex_xy.x_axis(label="σ"),
        height="460px",
        on_select_end=Dash.select,
    )

and the composed, multi-mark form (Level 2)::

    reflex_xy.chart(
        reflex_xy.scatter(x="x", y="y", color="mag"),
        reflex_xy.line(x="x", y="trend", width=2),
        reflex_xy.x_axis(label="Time"),
        data=Dash.cloud,
        height="460px",
    )

Both compile the real xy tree at page evaluation, run the zero-row plan
probe (`plan.py` — the mark/config validation gate, X1/X2, under the
core's `structural_probe()` mode: no synthetic data), check channel
names against the data var's TypedDict schema (R7), and mount the private
component with a `plan` digest plus the `data` handle var. Marks and chrome
are plain xy dataclass nodes — they never enter the Reflex tree
(Reflex child validation would refuse them; design decision 1 in the
options doc §5.6), which is why `chart(...)` here is a factory consuming
nodes, not a component taking children.

The kwarg partition of the flat form is **derived from signatures**, not
hand-listed: positional mark params are channels, keyword-only params are
options (xy's uniform convention), `Chart.__init__` provides the
chart-level names, and a small reserved set belongs to the component.
Underscore-prefixed signature params are xy-internal adapter knobs and are
excluded — derivation must not promote private names to public API.
Colliding mark options get flat aliases (`stroke_width` for `line`'s
`width`, `mark_<name>` otherwise); the resulting table is pinned by
`tests/reflex_adapter/test_factories.py` as public contract. Unknown
kwargs always error at page evaluation — with a did-you-mean suggestion
when a known name is close — and never silently become CSS (the R8 hazard
this partition exists to close); explicit ``style={...}`` carries CSS.
"""

from __future__ import annotations

import difflib
import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional, get_args, get_origin, get_type_hints, is_typeddict

import reflex as rx

import xy as _xy
from xy.components import Axis, Chart, Component, Legend, Theme

from .component import (
    _component,
    _merge_tailwind_class_tokens,
    _tailwind_class_manifest,
    _tailwind_class_tokens,
    _tailwind_scan_literal,
)
from .data_vars import validate_columns
from .handles import DataHandle
from .payload_asset import payload_asset
from .plan import ChartPlan, build_plan

__all__ = [
    "area_chart",
    "bar_chart",
    "box_chart",
    "chart",
    "column_chart",
    "contour_chart",
    "ecdf_chart",
    "error_band_chart",
    "errorbar_chart",
    "funnel_chart",
    "heatmap_chart",
    "hexbin_chart",
    "histogram_chart",
    "line_chart",
    "scatter_chart",
    "segments_chart",
    "stairs_chart",
    "stem_chart",
    "step_chart",
    "triangle_mesh_chart",
    "violin_chart",
]

#: Event triggers of the private XYChart component. Pinned against the
#: component class by tests so the two can never drift.
EVENT_TRIGGERS = frozenset(
    {
        "on_point_hover",
        "on_point_click",
        "on_select_end",
        "on_view_change",
        "on_hover",
        "on_animation_start",
        "on_animation_end",
    }
)

#: Names the component level owns in the flat form (the collision table's
#: "component/chart level wins" rule). A mark option with one of these names
#: is reachable through its generated alias instead.
COMPONENT_RESERVED = frozenset(
    {
        "width",
        "height",
        "opacity",
        "style",
        "class_name",
        "key",
        "animation",
        "id",
        "data",
        "figure",
        "token",
        "plan",
        "src",
        "tooltip",
        "tailwind_classes",
    }
)

#: Chrome slots the flat form accepts as kwargs. x_axis/y_axis are
#: type-dispatched: an Axis node is chrome, a string is the mark's axis id.
_CHROME_KWARGS = ("x_axis", "y_axis", "legend", "theme")

#: Chart.__init__ params that never partition to the chart tier: identity /
#: children / data are factory-owned; width/height/class_name/style collide
#: with the component (which wins); the on_* callables are the notebook
#: callback API — in Reflex, on_* means event-trigger props.
_CHART_EXCLUDED = frozenset(
    {
        "self",
        "kind",
        "children",
        "data",
        "width",
        "height",
        "class_name",
        "style",
        "on_hover",
        "on_click",
        "on_brush",
        "on_select",
        "on_view_change",
    }
)

CHART_PARAMS = frozenset(
    name for name in inspect.signature(Chart.__init__).parameters if name not in _CHART_EXCLUDED
)


def _mark_aliases(mark_params: frozenset[str]) -> dict[str, str]:
    """Generated flat aliases for mark options shadowed by the component.

    ``width`` prefers the natural ``stroke_width`` when the mark hasn't
    already claimed it (line's stroke width *is* its width); everything else
    is uniformly ``mark_<name>``.
    """
    aliases: dict[str, str] = {}
    for name in sorted(mark_params & COMPONENT_RESERVED):
        if name == "width" and "stroke_width" not in mark_params:
            aliases["stroke_width"] = name
        else:
            aliases[f"mark_{name}"] = name
    return aliases


@dataclass(frozen=True)
class _FlatKind:
    """One flat factory's derived partition."""

    chart_kind: str
    mark_factory: Any
    mark_params: frozenset[str]  # real mark kwargs (data excluded)
    aliases: dict[str, str]  # flat alias -> real mark param

    @property
    def flat_mark_params(self) -> frozenset[str]:
        plain = self.mark_params - COMPONENT_RESERVED - {"x_axis", "y_axis"}
        return plain | frozenset(self.aliases)

    @property
    def known(self) -> frozenset[str]:
        return (
            self.flat_mark_params
            | CHART_PARAMS
            | COMPONENT_RESERVED
            | frozenset(_CHROME_KWARGS)
            | EVENT_TRIGGERS
        )


def _flat_kind(chart_kind: str, mark_factory: Any) -> _FlatKind:
    # Underscore-prefixed params are xy's private adapter knobs (the pyplot
    # shim's `_artist_alpha`, `_marker_path`, …), not documented mark options.
    # Deriving the partition from the signature must not promote them to the
    # public flat surface — they would be silently accepted *and* offered as
    # did-you-mean suggestions, which is the opposite of the strict contract.
    params = frozenset(
        name
        for name in inspect.signature(mark_factory).parameters
        if name != "data" and not name.startswith("_")
    )
    return _FlatKind(
        chart_kind=chart_kind,
        mark_factory=mark_factory,
        mark_params=params,
        aliases=_mark_aliases(params),
    )


FLAT_KINDS: dict[str, _FlatKind] = {
    kind.chart_kind: kind
    for kind in (
        _flat_kind("scatter_chart", _xy.scatter),
        _flat_kind("line_chart", _xy.line),
        _flat_kind("histogram_chart", _xy.histogram),
        _flat_kind("bar_chart", _xy.bar),
        _flat_kind("area_chart", _xy.area),
        _flat_kind("step_chart", _xy.step),
        _flat_kind("stem_chart", _xy.stem),
        _flat_kind("column_chart", _xy.column),
        _flat_kind("errorbar_chart", _xy.errorbar),
        _flat_kind("error_band_chart", _xy.error_band),
        _flat_kind("segments_chart", _xy.segments),
        _flat_kind("funnel_chart", _xy.funnel),
        # Aggregating kinds: zero-row like everything else — under the
        # core's structural_probe() mode they validate config and skip
        # aggregation, so no synthetic data is ever invented for them.
        _flat_kind("box_chart", _xy.box),
        _flat_kind("violin_chart", _xy.violin),
        _flat_kind("ecdf_chart", _xy.ecdf),
        _flat_kind("hexbin_chart", _xy.hexbin),
        _flat_kind("contour_chart", _xy.contour),
        _flat_kind("heatmap_chart", _xy.heatmap),
        _flat_kind("stairs_chart", _xy.stairs),
        _flat_kind("triangle_mesh_chart", _xy.triangle_mesh),
    )
}


def _suggest(name: str, candidates: frozenset[str]) -> Optional[str]:
    matches = difflib.get_close_matches(name, sorted(candidates), n=1, cutoff=0.8)
    return matches[0] if matches else None


def _partition_flat(
    kind: _FlatKind, kwargs: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], list[Component], dict[str, Any]]:
    """Split flat kwargs into (mark, chart, chrome children, component)."""
    mark_kwargs: dict[str, Any] = {}
    chart_kwargs: dict[str, Any] = {}
    chrome: list[Component] = []
    component_kwargs: dict[str, Any] = {}
    for name, value in kwargs.items():
        if name in ("x_axis", "y_axis"):
            # Type-dispatched collision: an Axis node is a chrome child, a
            # string is the mark's axis-id option.
            if isinstance(value, Axis):
                chrome.append(value)
            elif isinstance(value, str):
                mark_kwargs[name] = value
            else:
                msg = (
                    f"{kind.chart_kind}() {name}= takes an axis node "
                    f"(reflex_xy.{name}(...)) or an axis-id string, got {type(value).__name__}"
                )
                raise TypeError(msg)
        elif name == "legend":
            if isinstance(value, Legend):
                chrome.append(value)
            elif isinstance(value, bool):
                chrome.append(_xy.legend(show=value))
            else:
                msg = (
                    f"{kind.chart_kind}() legend= takes reflex_xy.legend(...) or a bool, "
                    f"got {type(value).__name__}"
                )
                raise TypeError(msg)
        elif name == "theme":
            if not isinstance(value, Theme):
                msg = (
                    f"{kind.chart_kind}() theme= takes reflex_xy.theme(...), "
                    f"got {type(value).__name__}"
                )
                raise TypeError(msg)
            chrome.append(value)
        elif name in EVENT_TRIGGERS or name in COMPONENT_RESERVED:
            component_kwargs[name] = value
        elif name in kind.aliases:
            mark_kwargs[kind.aliases[name]] = value
        elif name in kind.mark_params:
            mark_kwargs[name] = value
        elif name in CHART_PARAMS:
            chart_kwargs[name] = value
        elif name.startswith("on_"):
            # Let the framework's create() raise its ValueError listing the
            # valid triggers (R8) — unless a near-miss lets us say better.
            suggestion = _suggest(name, EVENT_TRIGGERS)
            if suggestion is not None:
                msg = (
                    f"{kind.chart_kind}() got an unexpected event {name!r}; "
                    f"did you mean {suggestion!r}?"
                )
                raise TypeError(msg)
            component_kwargs[name] = value
        else:
            # Strict top-level kwargs: a typo far from every known name must
            # not silently become a CSS property on the mount (the promise
            # "unknown kwargs fail at page evaluation" holds without a
            # distance threshold). CSS stays available, explicitly, through
            # the reserved style={...} prop.
            suggestion = _suggest(name, kind.known)
            hint = f"; did you mean {suggestion!r}?" if suggestion is not None else "."
            msg = (
                f"{kind.chart_kind}() got an unexpected keyword {name!r}{hint} "
                f"CSS belongs in style={{...}}; chart/mark options are listed in "
                "the factory docs."
            )
            raise TypeError(msg)
    return mark_kwargs, chart_kwargs, chrome, component_kwargs


def _data_var_label(data: Any) -> str:
    declared = getattr(data, "_original", data)
    name = getattr(declared, "_name", None)
    return f"data var {name!r}" if isinstance(name, str) and name else "the data var"


def _schema_columns(data: Any) -> Optional[frozenset[str]]:
    """Column names carried by a ``DataHandle[Schema]``-typed var, if any."""
    var_type = getattr(data, "_var_type", None)
    if var_type is None or get_origin(var_type) is not DataHandle:
        return None
    args = get_args(var_type)
    if len(args) != 1 or not is_typeddict(args[0]):
        return None
    try:
        return frozenset(get_type_hints(args[0]))
    except Exception:  # noqa: BLE001 - schema annotations may not resolve here
        return None


def _check_schema(plan: ChartPlan, data: Any) -> None:
    """R7 compile check: every bound channel exists in the declared schema."""
    schema = _schema_columns(data)
    if schema is None:
        return
    unknown = [name for name in plan.columns if name not in schema]
    if unknown:
        label = _data_var_label(data)
        names = ", ".join(repr(name) for name in unknown)
        available = ", ".join(sorted(schema))
        noun = "columns" if len(unknown) > 1 else "column"
        msg = f"unknown {noun} {names} for {label}. Available columns: {available}"
        raise ValueError(msg)


def _mount(plan: ChartPlan, data: Any, component_kwargs: dict[str, Any]) -> Any:
    """Attach a compiled plan to its data source and build the component."""
    component_cls = _component()
    tooltip = component_kwargs.pop("tooltip", None)
    explicit_tailwind = _tailwind_class_tokens(component_kwargs.pop("tailwind_classes", None))
    component_kwargs.setdefault("width", "100%")
    component_kwargs.setdefault("height", "420px")

    if isinstance(data, (rx.Var, DataHandle)):
        # Live plan tier: digest baked into the JSX, columns resolved from
        # the handle at hydrate. The zero-row probe already inventoried the
        # chart's DOM classes, so live charts get automatic Tailwind
        # discovery (merged with any explicit inventory).
        component_kwargs["plan"] = plan.digest
        component_kwargs["data"] = data
        manifest = _merge_tailwind_class_tokens(plan.tailwind_classes, explicit_tailwind)
        if manifest:
            component_kwargs["tailwind_class_tokens"] = _tailwind_scan_literal(manifest)
    elif isinstance(data, Mapping):
        # Static tier: concrete columns bind now; the figure compiles to a
        # payload asset and renders kernel-less (works under `reflex export`).
        columns = validate_columns(data, source="data=")
        figure = plan.bind(columns, source="data=").figure()
        component_kwargs["src"] = payload_asset(figure)
        manifest = _merge_tailwind_class_tokens(_tailwind_class_manifest(figure), explicit_tailwind)
        if manifest:
            component_kwargs["tailwind_class_tokens"] = _tailwind_scan_literal(manifest)
    elif data is None:
        msg = (
            "data= is required: pass a @reflex_xy.data state var for a live "
            "chart, or a concrete mapping of columns for a static one"
        )
        raise TypeError(msg)
    else:
        msg = (
            "data= takes a @reflex_xy.data state var, a DataHandle, or a "
            f"concrete mapping of columns, got {type(data).__name__}"
        )
        raise TypeError(msg)
    if tooltip is not None:
        return component_cls.create(tooltip, **component_kwargs)
    return component_cls.create(**component_kwargs)


def _flat_chart(kind: _FlatKind, data: Any, kwargs: dict[str, Any]) -> Any:
    mark_kwargs, chart_kwargs, chrome, component_kwargs = _partition_flat(kind, kwargs)
    mark = kind.mark_factory(**mark_kwargs)
    if kind.chart_kind == "funnel_chart":
        # Funnel owns semantic chrome defaults: hidden symmetric cross axis,
        # reversed vertical stage axis, and hidden legend. Build its children
        # through the core factory so the Reflex flat form cannot drift from
        # those defaults; explicit chrome follows and therefore overrides it.
        children = _xy.funnel_chart(mark, *chrome).children
    else:
        children = (mark, *chrome)
    plan = build_plan(kind.chart_kind, children, chart_kwargs)
    _check_schema(plan, data)
    return _mount(plan, data, component_kwargs)


def scatter_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound scatter chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["scatter_chart"], data, kwargs)


def line_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound line chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["line_chart"], data, kwargs)


def histogram_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound histogram (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["histogram_chart"], data, kwargs)


def bar_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound bar chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["bar_chart"], data, kwargs)


def area_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound area chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["area_chart"], data, kwargs)


def step_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound step chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["step_chart"], data, kwargs)


def stem_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound stem chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["stem_chart"], data, kwargs)


def column_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound column chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["column_chart"], data, kwargs)


def errorbar_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound errorbar chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["errorbar_chart"], data, kwargs)


def error_band_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound error-band chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["error_band_chart"], data, kwargs)


def segments_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound segments chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["segments_chart"], data, kwargs)


def funnel_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound funnel chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["funnel_chart"], data, kwargs)


def box_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound box plot (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["box_chart"], data, kwargs)


def violin_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound violin plot (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["violin_chart"], data, kwargs)


def ecdf_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound ECDF chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["ecdf_chart"], data, kwargs)


def hexbin_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound hexbin chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["hexbin_chart"], data, kwargs)


def contour_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound contour chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["contour_chart"], data, kwargs)


def heatmap_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound heatmap (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["heatmap_chart"], data, kwargs)


def stairs_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound stairs chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["stairs_chart"], data, kwargs)


def triangle_mesh_chart(*, data: Any = None, **kwargs: Any) -> Any:
    """A data-bound triangle-mesh chart (flat form; see module doc)."""
    return _flat_chart(FLAT_KINDS["triangle_mesh_chart"], data, kwargs)


def chart(*sources: Any, data: Any = None, **kwargs: Any) -> Any:
    """Place a chart: composed xy nodes (data-bound), or the component tiers.

    With xy mark/annotation/chrome nodes, this is the composed data-bound
    form (Level 2): the nodes are compiled into a plan against ``data=``.
    With ``figure=`` or a positional Chart/Figure/token source, it is the
    rendering component of the escape hatch and static tiers —
    `component.chart` (§5 of reflex-integration.md), unchanged.
    """
    if sources and all(isinstance(source, Component) for source in sources):
        first = sources[0]
        if not (callable(getattr(first, "figure", None)) or isinstance(first, Chart)):
            return _composed_chart(sources, data, kwargs)
    from .component import chart as component_chart

    if data is not None:
        msg = (
            "chart() with data= takes xy mark/chrome nodes "
            "(e.g. chart(reflex_xy.scatter('x', 'y'), data=Dash.cloud))"
        )
        raise TypeError(msg)
    return component_chart(*sources, **kwargs)


def _composed_chart(nodes: tuple[Component, ...], data: Any, kwargs: dict[str, Any]) -> Any:
    """Level 2: consume plain xy nodes, compile the plan, mount the component."""
    chart_kwargs: dict[str, Any] = {}
    component_kwargs: dict[str, Any] = {}
    for name, value in kwargs.items():
        if name in EVENT_TRIGGERS or name in COMPONENT_RESERVED:
            component_kwargs[name] = value
        elif name in CHART_PARAMS:
            chart_kwargs[name] = value
        elif name.startswith("on_"):
            suggestion = _suggest(name, EVENT_TRIGGERS)
            if suggestion is not None:
                msg = f"chart() got an unexpected event {name!r}; did you mean {suggestion!r}?"
                raise TypeError(msg)
            component_kwargs[name] = value
        else:
            # Same strict rule as the flat factories: never silently CSS.
            suggestion = _suggest(name, CHART_PARAMS | COMPONENT_RESERVED | EVENT_TRIGGERS)
            hint = f"; did you mean {suggestion!r}?" if suggestion is not None else "."
            msg = f"chart() got an unexpected keyword {name!r}{hint} CSS belongs in style={{...}}."
            raise TypeError(msg)
    plan = build_plan("chart", tuple(nodes), chart_kwargs)
    _check_schema(plan, data)
    return _mount(plan, data, component_kwargs)
