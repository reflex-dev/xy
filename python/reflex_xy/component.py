"""The Reflex component: `reflex_xy.chart(...)`.

One factory, two chart sources (spec/design/reflex-integration.md §5):

    reflex_xy.chart(figure=Dash.chart)     # @reflex_xy.figure var / handle (live)
    reflex_xy.chart(xy.scatter_chart(...)) # a Chart directly (static tier)

The pre-handle positional forms — `chart(Dash.chart)` and
`chart(token_string)` — remain as a deprecation shim for one release cycle.

A live source compiles to the typed `figure` prop (`Var[FigureHandle]` —
wrong vars and raw strings fail at compile) and rides the shared-websocket
data plane. A `xy` Chart (or internal Figure) passed directly is
compiled to a static payload asset (payload_asset.py) and lands in the
`src` prop: the wrapper fetches the binary frame and runs the render client
kernel-less — no registry, no socket, works under `reflex export`.

The wrapper React component lives in `assets/XYChart.jsx` and is shipped as
a shared asset (the same mechanism reflex's own radix color-mode provider
uses for local JS). It is deliberately lazy: `rx.asset` symlinks into the
compiling app's `assets/` directory, so the component class is only built
the first time a chart is actually placed in a page tree.

Semantic events cross the normal Reflex event system as small JSON —
row dicts and selection summaries, never data buffers (§1 of the design):

    reflex_xy.chart(
        Dash.chart,
        on_point_hover=Dash.hovered,   # def hovered(self, row: dict)
        on_point_click=Dash.clicked,   # def clicked(self, row: dict)
        on_select_end=Dash.selected,   # def selected(self, sel: dict)
        on_view_change=Dash.viewed,    # def viewed(self, view: dict)
        height="480px",
    )

Point and selection events need the kernel, so they apply to live sources. A static
chart renders, pans/zooms, and resolves hover tooltips client-side; its small
``on_view_change`` payload can use the normal Reflex event prop without a data kernel.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable, Mapping, Set
from typing import Annotated, Any, Optional

import reflex as rx

from xy.facets import FacetGrid

from .assets import WRAPPER_TAG, register
from .handles import FigureHandle
from .payload_asset import payload_asset
from .registry import _figure_of

__all__ = ["chart"]

#: Event props that need the interaction kernel: they only ever fire for
#: live (token/figure) sources. A static payload (``src``) renders and
#: navigates client-side, so these would be silent no-ops — refused at
#: create() instead (see _validate_source_events).
_KERNEL_EVENT_PROPS = ("on_point_hover", "on_point_click", "on_select_end")

# Lazily-built component class (see module doc); Any because reflex Component
# metaclasses defeat static typing of the create() classmethod.
_component_cls: Optional[Any] = None


def _build_component_cls() -> Any:
    wrapper_library = register()

    class XYChart(rx.Component):
        """A xy figure bound to a registry token or a static payload."""

        # The shared-asset module path ($/public/external/reflex_xy/assets/…):
        # a local-JS library, never sent to the package manager.
        library = wrapper_library
        tag = WRAPPER_TAG

        # Live mode: the typed figure handle minted by @reflex_xy.figure /
        # register() / inline(). ``Var[FigureHandle]`` makes a wrong var
        # (``Dash.points``) or a raw string fail at create() — compile time
        # (fact R1). Exactly one of figure/token/src is ever set.
        figure: rx.Var[FigureHandle]
        # Deprecated live mode: the bare token string. Kept for one release
        # cycle; the wrapper accepts both (figure wins).
        token: rx.Var[str]
        # Static mode: URL of a payload asset (XYBF frame) to render
        # kernel-less.
        src: rx.Var[str]

        # Static charts carry their DOM class strings inside the binary XYBF
        # payload, where Reflex's TailwindV4Plugin cannot discover them.  This
        # compile-only prop mirrors those literal strings into the generated
        # JSX source so Tailwind can emit the corresponding utilities.  The
        # wrapper destructures and discards it; it never reaches the DOM.
        tailwind_class_tokens: rx.Var[str]

        # Semantic events out (small JSON by construction — §1). Point and
        # selection events are live-only because static charts have no row
        # resolution kernel; view changes are already complete client-side.
        #
        # Spelled `Annotated[rx.EventHandler, <args spec>]`, not the shorthand
        # `rx.EventHandler[<args spec>]` — the same object either way, since
        # `EventHandler.__class_getitem__` returns exactly this form and reflex
        # reads the spec back out of `__metadata__`. Only the shorthand is a
        # runtime-only DSL: `EventHandler` is not generic, so subscripting it is
        # invalid in a type expression and checkers reject it. Don't fold it back.
        on_point_hover: Annotated[rx.EventHandler, lambda row: [row]]
        on_point_click: Annotated[rx.EventHandler, lambda row: [row]]
        on_select_end: Annotated[rx.EventHandler, lambda selection: [selection]]
        on_view_change: Annotated[rx.EventHandler, lambda view: [view]]
        on_animation_start: Annotated[rx.EventHandler, lambda event: [event]]
        on_animation_end: Annotated[rx.EventHandler, lambda event: [event]]
        # Structured hover payload (view-state.md §7.1): resolved fully in the
        # browser — cursor px/data coordinates plus the picked points — so it
        # works on static charts too. `on_point_hover` stays the narrow
        # legacy row form; new code uses this.
        on_hover: Annotated[rx.EventHandler, lambda payload: [payload]]

        @classmethod
        def create(cls, *children: Any, **props: Any) -> Any:
            # Compile-time validation the framework can't do for us
            # (recharts pattern, fact R5): kernel-backed events on a static
            # source would be silent no-ops at runtime — fail the compile
            # with the reason instead.
            # `on_point_hover=None` is an explicitly disabled handler: drop it
            # (Reflex would reject a None trigger) so the value-based static
            # check below and the framework both see "no handler".
            props = {
                name: value
                for name, value in props.items()
                if value is not None or not name.startswith("on_")
            }
            if props.get("src") is not None:
                offenders = [name for name in _KERNEL_EVENT_PROPS if props.get(name) is not None]
                if offenders:
                    msg = (
                        f"{', '.join(offenders)} need the interaction kernel and never "
                        "fire on a static chart source (a Chart/Figure compiled to a "
                        "payload asset). Serve the figure live instead — a "
                        "@reflex_xy.figure state var or register()/inline() — "
                        "or drop the handler(s). Client-side "
                        "events (on_hover, on_view_change) work on static charts."
                    )
                    raise ValueError(msg)
            return super().create(*children, **props)

    # The class is created lazily inside this function; reflex derives JS
    # identifiers from __qualname__, and "<locals>" would leak an illegal
    # "<" into compiled import names. Present it as a module-level class.
    XYChart.__qualname__ = "XYChart"
    XYChart.__module__ = __name__
    return XYChart


def _component() -> Any:
    """Return the lazily constructed Reflex component class."""
    global _component_cls
    if _component_cls is None:
        _component_cls = _build_component_cls()
    return _component_cls


def _is_chart_like(source: Any) -> bool:
    """A public `xy.Chart` (has .figure()) or an internal Figure."""
    return callable(getattr(source, "figure", None)) or callable(
        getattr(source, "build_payload", None)
    )


def _tailwind_class_manifest(figure: Any) -> str:
    """Return every static-chart DOM class string as one scan-only literal.

    The inventory itself is core-Figure knowledge and lives on
    :meth:`xy.Figure.dom_class_strings`; reading the built figure avoids a
    second payload compilation (which can be expensive for large charts).
    """
    return " ".join(figure.dom_class_strings())


def _tailwind_class_tokens(value: Optional[str | Iterable[str]]) -> str:
    """Normalize a build-time Tailwind class inventory.

    Live figure tokens cannot expose the classes inside their runtime payload
    to Tailwind's source scanner. Accept either one class string or an ordered
    iterable of class strings, require concrete strings (never a reactive
    ``Var``), reject mappings and unordered sets, and de-duplicate individual
    utility tokens while preserving order.
    """
    if value is None:
        return ""
    if isinstance(value, (Mapping, Set)):
        raise TypeError(
            "tailwind_classes must be a string or ordered iterable of strings, not a mapping or set"
        )
    values: Iterable[Any] = (value,) if isinstance(value, str) else value
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise TypeError("tailwind_classes must be a string or ordered iterable of strings") from exc

    tokens: list[str] = []
    seen: set[str] = set()
    for class_string in iterator:
        if not isinstance(class_string, str):
            raise TypeError("tailwind_classes must contain only strings")
        for token in class_string.split():
            if token not in seen:
                seen.add(token)
                tokens.append(token)
    return " ".join(tokens)


def _merge_tailwind_class_tokens(*manifests: str) -> str:
    """Join scan manifests without emitting duplicate utility tokens."""
    return _tailwind_class_tokens(manifests)


def _tailwind_scan_literal(manifest: str) -> rx.Var[str]:
    """Expose a Tailwind inventory verbatim in generated source.

    Reflex serializes ordinary string props as JSON.  That is correct at
    runtime, but Tailwind scans the generated source without evaluating
    JavaScript: quotes, backslashes, and non-ASCII characters therefore become
    different candidate strings after JSON escaping.  Put the normalized
    manifest in a line comment instead.  Tailwind sees the exact class tokens,
    while the expression evaluates to an empty string that ``XYChart`` already
    discards.

    ``_tailwind_class_tokens`` replaces every whitespace run with one ASCII
    space, so the manifest cannot terminate the line comment.
    """
    manifest = _tailwind_class_tokens(manifest)
    return rx.Var(
        _js_expr=f'("" // {manifest}\n)',
        _var_type=str,
    )


def _facet_grid(
    grid: Any,
    *,
    tooltip: Any,
    tailwind_manifest: str,
    props: dict[str, Any],
) -> Any:
    """Render a core ``FacetGrid`` as a responsive Reflex CSS grid.

    A facet grid intentionally has no single wire payload: every panel is an
    independent Figure with its own axes and LOD budget.  Preserve that core
    contract by mounting one static XYChart per panel rather than trying to
    feed the grid itself to :func:`payload_asset`.
    """
    # Semantic handlers belong on every panel. Layout/identity props belong
    # only on the grid container (notably, duplicating an id would be invalid
    # HTML), while each panel retains the dimensions chosen by facet_chart.
    event_props = {key: value for key, value in props.items() if key.startswith("on_")}
    panels = []
    # grid.labels needs no separate strip: facet_chart builds every panel
    # figure with its facet label as the figure title, so the label ships
    # inside each panel's payload and renders as the panel heading (the same
    # contract FacetGrid.to_html relies on).
    for figure in grid.figures:
        panel_props = dict(event_props)
        panel_props.update(width="100%", height=f"{grid.panel_height}px")
        panel_props["src"] = payload_asset(figure)
        class_manifest = _merge_tailwind_class_tokens(
            _tailwind_class_manifest(figure),
            tailwind_manifest,
        )
        if class_manifest:
            panel_props["tailwind_class_tokens"] = _tailwind_scan_literal(class_manifest)
        component_cls = _component()
        panel = (
            component_cls.create(tooltip, **panel_props)
            if tooltip
            else component_cls.create(**panel_props)
        )
        panels.append(panel)

    grid_body = rx.box(
        *panels,
        class_name="xy-facet-grid",
        display="grid",
        grid_template_columns=f"repeat({grid.cols}, minmax(0, 1fr))",
        gap=f"{grid.gap}px",
        width="100%",
    )
    children = [grid_body]
    if grid.title:
        children.insert(
            0,
            rx.text(
                grid.title,
                class_name="xy-facet-title",
                height=f"{grid._TITLE_H}px",
                line_height=f"{grid._TITLE_H}px",
                text_align="center",
                font_weight="600",
            ),
        )
    container_props = {key: value for key, value in props.items() if key not in event_props}
    container_class = container_props.pop("class_name", "")
    container_props.setdefault("width", "100%")
    container_props.setdefault("height", f"{grid.grid_height + grid._title_height}px")
    return rx.box(
        *children,
        class_name=f"xy-facet-document {container_class}".strip(),
        **container_props,
    )


def _is_handle_var(source: Any) -> bool:
    """A Reflex Var whose declared value type is FigureHandle."""
    var_type = getattr(source, "_var_type", None)
    return isinstance(var_type, type) and issubclass(var_type, FigureHandle)


def _warn_positional(replacement: str) -> None:
    warnings.warn(
        f"positional reflex_xy.chart(source) is deprecated for live sources; use {replacement}",
        DeprecationWarning,
        stacklevel=3,
    )


def chart(
    source: Any = None,
    *,
    figure: Any = None,
    tooltip: Any = None,
    tailwind_classes: Optional[str | Iterable[str]] = None,
    **props: Any,
) -> Any:
    """Place a xy chart.

    ``figure=`` is the live, kernel-backed form: a ``@reflex_xy.figure``
    state var, or the :class:`~reflex_xy.handles.FigureHandle` returned by
    ``register()``/``inline()``. The prop is typed ``Var[FigureHandle]``, so
    the wrong var or a raw string fails at compile with the framework's own
    ``TypeError``.

    A positional `source` remains supported: an ``xy`` Chart/Figure renders
    as a static payload asset with client-side interactivity only (see
    module doc; this is the static tier and stays positional), while
    var/handle/token-string sources are the deprecated pre-handle spelling
    of ``figure=`` and warn.

    `tooltip=` mounts a Reflex component as the chart tooltip: the render
    client positions it with the built-in tooltip's placement logic (the
    built-in tooltip is suppressed while it is mounted) and the `on_hover`
    payload carries the data to show. A Chart source that declares
    `xy.tooltip(render=...)` mounts that component automatically.

    Sizing: the outer element defaults to `width: 100%` and a 420px height;
    pass `width=`/`height=` (or any style prop) to override. Charts built
    with `width="100%"` track the element responsively.

    `tailwind_classes=` is a build-time inventory for token/Var-backed charts,
    whose runtime payload is otherwise invisible to Tailwind's source scan.
    Pass complete literal utility strings (or an ordered iterable of them).
    Static Chart/Figure sources are discovered automatically; an explicit
    inventory is merged with their discovered classes.
    """
    component_cls = _component()
    tailwind_manifest = _tailwind_class_tokens(tailwind_classes)
    if figure is not None and source is not None:
        msg = "reflex_xy.chart() takes a positional source or figure=, not both"
        raise TypeError(msg)
    if figure is None and source is None:
        msg = "reflex_xy.chart() needs a chart source: figure=, or a positional Chart/Figure"
        raise TypeError(msg)
    if figure is None and (
        isinstance(source, FigureHandle) or (isinstance(source, rx.Var) and _is_handle_var(source))
    ):
        # Pre-handle spelling: the var/handle used to land in the str `token`
        # prop. Handles ride the typed prop now; legacy str-typed vars keep
        # the old wire path below.
        _warn_positional("chart(figure=...)")
        figure, source = source, None
    if figure is not None:
        props.setdefault("width", "100%")
        props.setdefault("height", "420px")
        props["figure"] = figure
        if tailwind_manifest:
            props["tailwind_class_tokens"] = _tailwind_scan_literal(tailwind_manifest)
    elif isinstance(source, (str, rx.Var)):
        _warn_positional(
            "chart(figure=...) — register()/inline() return a FigureHandle, "
            "@reflex_xy.figure vars are FigureHandle-valued, and a stored bare "
            "token wraps as figure=FigureHandle(token) (the typed prop rejects "
            "raw strings)"
        )
        props.setdefault("width", "100%")
        props.setdefault("height", "420px")
        props["token"] = source
        if tailwind_manifest:
            props["tailwind_class_tokens"] = _tailwind_scan_literal(tailwind_manifest)
    elif _is_chart_like(source):
        # Build a public Chart once, then reuse the cached Figure for both the
        # payload and its Tailwind scan manifest.  In particular, do not call
        # build_payload() just to discover classes: that would duplicate the
        # largest part of static-chart compilation.
        chrome_components = getattr(source, "chrome_components", None)
        if tooltip is None and callable(chrome_components):
            tooltip = chrome_components().get("tooltip")
        figure = _figure_of(source)
        if isinstance(figure, FacetGrid):
            return _facet_grid(
                figure,
                tooltip=tooltip,
                tailwind_manifest=tailwind_manifest,
                props=props,
            )
        props.setdefault("width", "100%")
        props.setdefault("height", "420px")
        props["src"] = payload_asset(figure)
        class_manifest = _merge_tailwind_class_tokens(
            _tailwind_class_manifest(figure),
            tailwind_manifest,
        )
        if class_manifest:
            props["tailwind_class_tokens"] = _tailwind_scan_literal(class_manifest)
    else:
        msg = (
            "reflex_xy.chart() takes figure= (a @reflex_xy.figure var or "
            "FigureHandle) or a positional xy Chart/Figure, got "
            f"{type(source).__name__}"
        )
        raise TypeError(msg)
    if tooltip is not None:
        return component_cls.create(tooltip, **props)
    return component_cls.create(**props)
