"""A declarative, composition-based component API.

The *feel* is Reflex's (reflex.dev) Recharts components — a chart container with
mark and axis children, snake_case keyword props, `data=` + column-name
resolution, and `on_*` event props — but fastcharts does **not** import or depend
on Reflex. It's the same ergonomics on top of the fastcharts engine (`Figure`):

    import fastcharts as fc

    fc.scatter_chart(
        fc.scatter(x="sepal_w", y="sepal_l", color="species", size="petal_l", data=df),
        fc.x_axis(label="sepal width"),
        fc.y_axis(label="sepal length"),
        fc.legend(),
        title="Iris",
        on_hover=lambda row: print(row),
        on_select=lambda sel: print(len(sel.index), "points"),
    )

Marks accept `x`/`y`/`color`/`size` as arrays *or* as string column names into
`data` (a DataFrame, dict, or anything indexable) — the Reflex/Recharts
`data_key` idiom, read more directly. Everything composes into a `Figure`, so a
chart renders in notebooks and exports to HTML exactly like the fluent API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union

from .figure import Figure

# ---------------------------------------------------------------------------
# Component tree (lightweight declarative specs — no rendering here)
# ---------------------------------------------------------------------------


class Component:
    """Base for every fastcharts component (Reflex-style: props + children)."""


@dataclass
class Mark(Component):
    kind: str  # "scatter" | "line"
    x: Any
    y: Any
    data: Any = None
    name: Optional[str] = None
    props: dict = field(default_factory=dict)


@dataclass
class Axis(Component):
    which: str  # "x" | "y"
    label: Optional[str] = None
    type_: Optional[str] = None  # "linear" | "time" (auto-detected if None)


@dataclass
class Legend(Component):
    show: bool = True


# ---------------------------------------------------------------------------
# Factory functions (the public, Reflex-flavored surface)
# ---------------------------------------------------------------------------


def scatter(
    x: Union[str, Any] = None,
    y: Union[str, Any] = None,
    *,
    data: Any = None,
    color: Union[str, Any, None] = None,
    size: Union[str, float, Any] = 4.0,
    name: Optional[str] = None,
    colormap: str = "viridis",
    size_range: tuple[float, float] = (2.0, 18.0),
    opacity: float = 0.8,
    density: Optional[bool] = None,
) -> Mark:
    """A scatter series. `x`/`y`/`color`/`size` may be arrays or column names in
    `data`. `color` is auto-typed (numeric → colormap, categorical → palette);
    large series auto-aggregate to a Tier-2 density surface (§5)."""
    return Mark(
        kind="scatter",
        x=x,
        y=y,
        data=data,
        name=name,
        props={
            "color": color,
            "size": size,
            "colormap": colormap,
            "size_range": size_range,
            "opacity": opacity,
            "density": density,
        },
    )


def line(
    x: Union[str, Any] = None,
    y: Union[str, Any] = None,
    *,
    data: Any = None,
    name: Optional[str] = None,
    color: Optional[str] = None,
    width: float = 1.5,
    opacity: float = 1.0,
) -> Mark:
    """A line series (M4-decimated above the threshold, §5 Tier 1)."""
    return Mark(
        kind="line",
        x=x,
        y=y,
        data=data,
        name=name,
        props={"color": color, "width": width, "opacity": opacity},
    )


def candlestick(
    x: Union[str, Any] = None,
    open: Union[str, Any] = None,  # noqa: A002 - OHLC domain naming
    high: Union[str, Any] = None,
    low: Union[str, Any] = None,
    close: Union[str, Any] = None,
    *,
    data: Any = None,
    name: Optional[str] = None,
    up_color: str = "#26a69a",
    down_color: str = "#ef5350",
    width_frac: float = 0.7,
    opacity: float = 1.0,
) -> Mark:
    """An OHLC candlestick series (OHLC-bucketed above the threshold, §5)."""
    return Mark(
        kind="candlestick",
        x=x,
        y=close,  # close doubles as the xy `y` fallback
        data=data,
        name=name,
        props={
            "open": open,
            "high": high,
            "low": low,
            "close": close,
            "up_color": up_color,
            "down_color": down_color,
            "width_frac": width_frac,
            "opacity": opacity,
        },
    )


def ohlc(
    x: Union[str, Any] = None,
    open: Union[str, Any] = None,  # noqa: A002
    high: Union[str, Any] = None,
    low: Union[str, Any] = None,
    close: Union[str, Any] = None,
    *,
    data: Any = None,
    name: Optional[str] = None,
    up_color: str = "#26a69a",
    down_color: str = "#ef5350",
    width_frac: float = 0.7,
    opacity: float = 1.0,
) -> Mark:
    """An OHLC bar series (tick bars; OHLC-bucketed above the threshold, §5)."""
    return Mark(
        kind="ohlc",
        x=x,
        y=close,
        data=data,
        name=name,
        props={
            "open": open,
            "high": high,
            "low": low,
            "close": close,
            "up_color": up_color,
            "down_color": down_color,
            "width_frac": width_frac,
            "opacity": opacity,
        },
    )


def x_axis(*, label: Optional[str] = None, type_: Optional[str] = None) -> Axis:
    return Axis(which="x", label=label, type_=type_)


def y_axis(*, label: Optional[str] = None, type_: Optional[str] = None) -> Axis:
    return Axis(which="y", label=label, type_=type_)


def legend(show: bool = True) -> Legend:
    return Legend(show=show)


# ---------------------------------------------------------------------------
# Chart container
# ---------------------------------------------------------------------------


def _resolve(data: Any, key: Any) -> Any:
    """Reflex `data_key` idiom: a string names a column in `data`; anything else
    is passed through as the values themselves."""
    if isinstance(key, str):
        if data is None:
            raise ValueError(
                f"column name {key!r} given but no data= provided; pass data=df "
                "or give x/y/color/size as arrays"
            )
        try:
            return data[key]
        except (KeyError, TypeError, IndexError) as e:
            raise ValueError(f"column {key!r} not found in data") from e
    return key


class Chart(Component):
    """Composes marks + axis/legend children into a `Figure`. Renders in
    notebooks and exports to HTML via the underlying engine."""

    def __init__(
        self,
        kind: str,
        children: tuple[Component, ...],
        *,
        title: Optional[str] = None,
        width: "int | str" = 900,  # pixels, or "100%" to fill the parent
        height: "int | str" = 420,  # pixels, or "100%" (parent needs a height)
        data: Any = None,
        on_hover: Optional[Callable[[dict], None]] = None,
        on_select: Optional[Callable[[Any], None]] = None,
    ) -> None:
        self.kind = kind
        self.children = children
        self.title = title
        self.width = width
        self.height = height
        self.data = data  # chart-level default data for marks that omit their own
        self.on_hover = on_hover
        self.on_select = on_select
        self._figure: Optional[Figure] = None
        self._widget: Any = None

    # -- build ---------------------------------------------------------------

    def figure(self) -> Figure:
        """The composed `Figure` (built once, cached)."""
        if self._figure is not None:
            return self._figure

        marks = [c for c in self.children if isinstance(c, Mark)]
        axes = {c.which: c for c in self.children if isinstance(c, Axis)}
        legends = [c for c in self.children if isinstance(c, Legend)]
        unknown = [c for c in self.children if not isinstance(c, (Mark, Axis, Legend))]
        if unknown:
            raise TypeError(
                f"{self.kind}() children must be marks/axes/legend, got "
                f"{[type(c).__name__ for c in unknown]}"
            )

        xa, ya = axes.get("x"), axes.get("y")
        fig = Figure(
            width=self.width,
            height=self.height,
            title=self.title,
            x_label=xa.label if xa else None,
            y_label=ya.label if ya else None,
        )
        for axis in (xa, ya):
            if axis and axis.type_ == "log":
                import warnings

                warnings.warn(
                    "log axes are on the v1 roadmap (§30) but not implemented "
                    "yet; falling back to linear.",
                    RuntimeWarning,
                    stacklevel=2,
                )

        for m in marks:
            data = m.data if m.data is not None else self.data
            applier = _MARK_APPLIERS.get(m.kind)
            if applier is None:
                raise TypeError(f"no applier registered for mark kind {m.kind!r}")
            applier(fig, m, data)

        if legends and not legends[-1].show:
            fig.show_legend = False
        self._figure = fig
        return fig

    # -- render (delegates to the engine) ------------------------------------

    def widget(self) -> Any:
        if self._widget is None:
            from .widget import FigureWidget

            self._widget = FigureWidget(
                self.figure(), on_hover=self.on_hover, on_select=self.on_select
            )
        return self._widget

    def show(self) -> Any:
        return self.widget()

    def _ipython_display_(self) -> None:
        from IPython.display import display  # type: ignore[import-not-found]

        display(self.widget())

    def to_html(self, path: Optional[str] = None) -> str:
        return self.figure().to_html(path)

    def memory_report(self) -> dict:
        return self.figure().memory_report()


def _resolve_color(data: Any, color: Any) -> Any:
    """Disambiguate a string `color`: a CSS color is a constant; any other
    string is a column name resolved from `data` (Reflex data_key idiom)."""
    if not isinstance(color, str):
        return color  # None, or an already-materialized array
    if _looks_like_css(color):
        return color  # constant color
    return _resolve(data, color)  # column name → values (raises if no data)


def _looks_like_css(s: str) -> bool:
    """Heuristic: a bare color string vs a column name. Hex, rgb(), and common
    named colors are treated as constant colors; everything else is a column."""
    if s.startswith("#") or s.startswith("rgb") or s.startswith("hsl") or s.startswith("oklch"):
        return True
    return s.lower() in _CSS_NAMES


_CSS_NAMES = {
    "black",
    "white",
    "red",
    "green",
    "blue",
    "yellow",
    "orange",
    "purple",
    "gray",
    "grey",
    "cyan",
    "magenta",
    "pink",
    "brown",
    "teal",
    "navy",
    "gold",
    "silver",
    "maroon",
    "olive",
    "lime",
    "aqua",
    "fuchsia",
    "transparent",
}


# ---------------------------------------------------------------------------
# Mark appliers — one per mark kind, mapping a declarative Mark onto a Figure
# call with its (data-resolved) props. Register a new chart type here; the
# Chart container dispatches through this table, so figure() never grows a
# per-kind branch.
# ---------------------------------------------------------------------------


def _apply_scatter(fig: Figure, m: Mark, data: Any) -> None:
    size = m.props["size"]
    fig.scatter(
        _resolve(data, m.x),
        _resolve(data, m.y),
        name=m.name,
        color=_resolve_color(data, m.props["color"]),
        size=_resolve(data, size) if isinstance(size, str) else size,
        colormap=m.props["colormap"],
        size_range=m.props["size_range"],
        opacity=m.props["opacity"],
        density=m.props["density"],
    )


def _apply_line(fig: Figure, m: Mark, data: Any) -> None:
    fig.line(
        _resolve(data, m.x),
        _resolve(data, m.y),
        name=m.name,
        color=m.props["color"],
        width=m.props["width"],
        opacity=m.props["opacity"],
    )


def _apply_candlestick(fig: Figure, m: Mark, data: Any) -> None:
    p = m.props
    fig.candlestick(
        _resolve(data, m.x),
        _resolve(data, p["open"]),
        _resolve(data, p["high"]),
        _resolve(data, p["low"]),
        _resolve(data, p["close"]),
        name=m.name,
        up_color=p["up_color"],
        down_color=p["down_color"],
        width_frac=p["width_frac"],
        opacity=p["opacity"],
    )


def _apply_ohlc(fig: Figure, m: Mark, data: Any) -> None:
    p = m.props
    fig.ohlc(
        _resolve(data, m.x),
        _resolve(data, p["open"]),
        _resolve(data, p["high"]),
        _resolve(data, p["low"]),
        _resolve(data, p["close"]),
        name=m.name,
        up_color=p["up_color"],
        down_color=p["down_color"],
        width_frac=p["width_frac"],
        opacity=p["opacity"],
    )


_MARK_APPLIERS: dict[str, Callable[[Figure, Mark, Any], None]] = {
    "scatter": _apply_scatter,
    "line": _apply_line,
    "candlestick": _apply_candlestick,
    "ohlc": _apply_ohlc,
}


def scatter_chart(*children: Component, **props: Any) -> Chart:
    """A scatter chart composing `scatter` marks and axis/legend children."""
    return Chart("scatter_chart", children, **props)


def line_chart(*children: Component, **props: Any) -> Chart:
    """A line chart composing `line` marks and axis/legend children."""
    return Chart("line_chart", children, **props)


def candlestick_chart(*children: Component, **props: Any) -> Chart:
    """A candlestick chart composing `candlestick` marks and axis/legend children."""
    return Chart("candlestick_chart", children, **props)


def ohlc_chart(*children: Component, **props: Any) -> Chart:
    """An OHLC bar chart composing `ohlc` marks and axis/legend children."""
    return Chart("ohlc_chart", children, **props)
