"""The Reflex component: `reflex_xy.chart(...)`.

One factory, three chart sources (spec/design/reflex-integration.md §5):

    reflex_xy.chart(Dash.chart)            # @reflex_xy.figure state var (live)
    reflex_xy.chart(some_token_string)     # register()/inline() token (live)
    reflex_xy.chart(xy.scatter_chart(...)) # a Chart directly (static tier)

A live source compiles to the `token` prop and rides the shared-websocket
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

from typing import Any, Optional

import reflex as rx

from xy.facets import FacetGrid

from .assets import WRAPPER_TAG, register
from .payload_asset import payload_asset
from .registry import _figure_of

__all__ = ["chart"]

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

        # Live mode: the figure token minted by @reflex_xy.figure /
        # register() / inline(). Exactly one of token/src is ever set.
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
        on_point_hover: rx.EventHandler[lambda row: [row]]
        on_point_click: rx.EventHandler[lambda row: [row]]
        on_select_end: rx.EventHandler[lambda selection: [selection]]
        on_view_change: rx.EventHandler[lambda view: [view]]
        on_animation_start: rx.EventHandler[lambda event: [event]]
        on_animation_end: rx.EventHandler[lambda event: [event]]
        # Structured hover payload (view-state.md §7.1): resolved fully in the
        # browser — cursor px/data coordinates plus the picked points — so it
        # works on static charts too. `on_point_hover` stays the narrow
        # legacy row form; new code uses this.
        on_hover: rx.EventHandler[lambda payload: [payload]]

    # The class is created lazily inside this function; reflex derives JS
    # identifiers from __qualname__, and "<locals>" would leak an illegal
    # "<" into compiled import names. Present it as a module-level class.
    XYChart.__qualname__ = "XYChart"
    XYChart.__module__ = __name__
    return XYChart


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


def _facet_grid(grid: Any, *, tooltip: Any, props: dict[str, Any]) -> Any:
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
        class_manifest = _tailwind_class_manifest(figure)
        if class_manifest:
            panel_props["tailwind_class_tokens"] = class_manifest
        panel = (
            _component_cls.create(tooltip, **panel_props)
            if tooltip
            else _component_cls.create(**panel_props)
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


def chart(source: Any, *, tooltip: Any = None, **props: Any) -> Any:
    """Place a xy chart.

    `source` is a figure token (a `@reflex_xy.figure` state var, or a
    `register()`/`inline()` token string) for a live, kernel-backed chart —
    or a `xy` Chart/Figure directly, which renders as a static
    payload asset with client-side interactivity only (see module doc).

    `tooltip=` mounts a Reflex component as the chart tooltip: the render
    client positions it with the built-in tooltip's placement logic (the
    built-in tooltip is suppressed while it is mounted) and the `on_hover`
    payload carries the data to show. A Chart source that declares
    `xy.tooltip(render=...)` mounts that component automatically.

    Sizing: the outer element defaults to `width: 100%` and a 420px height;
    pass `width=`/`height=` (or any style prop) to override. Charts built
    with `width="100%"` track the element responsively.
    """
    global _component_cls
    if _component_cls is None:
        _component_cls = _build_component_cls()
    if isinstance(source, (str, rx.Var)):
        props.setdefault("width", "100%")
        props.setdefault("height", "420px")
        props["token"] = source
    elif _is_chart_like(source):
        # Build a public Chart once, then reuse the cached Figure for both the
        # payload and its Tailwind scan manifest.  In particular, do not call
        # build_payload() just to discover classes: that would duplicate the
        # largest part of static-chart compilation.
        if tooltip is None and callable(getattr(source, "chrome_components", None)):
            tooltip = source.chrome_components().get("tooltip")
        figure = _figure_of(source)
        if isinstance(figure, FacetGrid):
            return _facet_grid(figure, tooltip=tooltip, props=props)
        props.setdefault("width", "100%")
        props.setdefault("height", "420px")
        props["src"] = payload_asset(figure)
        class_manifest = _tailwind_class_manifest(figure)
        if class_manifest:
            props["tailwind_class_tokens"] = class_manifest
    else:
        msg = (
            "reflex_xy.chart() takes a figure token (state var or string) or a "
            f"xy Chart/Figure, got {type(source).__name__}"
        )
        raise TypeError(msg)
    if tooltip is not None:
        return _component_cls.create(tooltip, **props)
    return _component_cls.create(**props)
