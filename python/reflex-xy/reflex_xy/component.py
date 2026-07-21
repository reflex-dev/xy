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


def chart(source: Any, **props: Any) -> Any:
    """Place a xy chart.

    `source` is a figure token (a `@reflex_xy.figure` state var, or a
    `register()`/`inline()` token string) for a live, kernel-backed chart —
    or a `xy` Chart/Figure directly, which renders as a static
    payload asset with client-side interactivity only (see module doc).

    Sizing: the outer element defaults to `width: 100%` and a 420px height;
    pass `width=`/`height=` (or any style prop) to override. Charts built
    with `width="100%"` track the element responsively.
    """
    global _component_cls
    if _component_cls is None:
        _component_cls = _build_component_cls()
    props.setdefault("width", "100%")
    props.setdefault("height", "420px")
    if isinstance(source, (str, rx.Var)):
        props["token"] = source
    elif _is_chart_like(source):
        # Build a public Chart once, then reuse the cached Figure for both the
        # payload and its Tailwind scan manifest.  In particular, do not call
        # build_payload() just to discover classes: that would duplicate the
        # largest part of static-chart compilation.
        figure = _figure_of(source)
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
    return _component_cls.create(**props)
