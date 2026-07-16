"""The Reflex component: `reflex_xy.chart(State.figure_var, ...)`.

The wrapper React component lives in `assets/XYChart.jsx` and is shipped as
a shared asset (the same mechanism reflex's own radix color-mode provider
uses for local JS). It is deliberately lazy: `rx.asset` symlinks into the
compiling app's `assets/` directory, so the component class is only built
the first time a chart is actually placed in a page tree.

Semantic events cross the normal Reflex event system as small JSON —
row dicts and selection summaries, never data buffers (§2 of the design):

    reflex_xy.chart(
        Dash.chart,
        on_point_hover=Dash.hovered,   # def hovered(self, row: dict)
        on_point_click=Dash.clicked,   # def clicked(self, row: dict)
        on_select_end=Dash.selected,   # def selected(self, sel: dict)
        on_view_change=Dash.viewed,    # def viewed(self, view: dict)
        height="480px",
    )
"""

from __future__ import annotations

from typing import Any, Optional

import reflex as rx

from .assets import WRAPPER_TAG, register

__all__ = ["chart"]

# Lazily-built component class (see module doc); Any because reflex Component
# metaclasses defeat static typing of the create() classmethod.
_component_cls: Optional[Any] = None


def _build_component_cls() -> Any:
    wrapper_library = register()

    class XYChart(rx.Component):
        """A xy figure bound to a registry token."""

        # The shared-asset module path ($/public/external/reflex_xy/assets/…):
        # a local-JS library, never sent to the package manager.
        library = wrapper_library
        tag = WRAPPER_TAG

        # The figure token minted by @reflex_xy.figure (or register()).
        token: rx.Var[str]

        # Semantic events out (small JSON by construction — §2).
        on_point_hover: rx.EventHandler[lambda row: [row]]
        on_point_click: rx.EventHandler[lambda row: [row]]
        on_select_end: rx.EventHandler[lambda selection: [selection]]
        on_view_change: rx.EventHandler[lambda view: [view]]

    # The class is created lazily inside this function; reflex derives JS
    # identifiers from __qualname__, and "<locals>" would leak an illegal
    # "<" into compiled import names. Present it as a module-level class.
    XYChart.__qualname__ = "XYChart"
    XYChart.__module__ = __name__
    return XYChart


def chart(token: Any, **props: Any) -> Any:
    """Place a xy chart bound to `token` (a `@reflex_xy.figure` var
    or a `reflex_xy.register()` token string).

    Sizing: the outer element defaults to `width: 100%` and a 420px height;
    pass `width=`/`height=` (or any style prop) to override. Charts built
    with `width="100%"` track the element responsively.
    """
    global _component_cls
    if _component_cls is None:
        _component_cls = _build_component_cls()
    props.setdefault("width", "100%")
    props.setdefault("height", "420px")
    return _component_cls.create(token=token, **props)
