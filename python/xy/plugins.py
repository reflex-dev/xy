"""Third-party mark plugins — the v0 of the dossier's §24 extensibility story.

§24 describes a registered mark plugin as three things: a calc function over
columns, *either* a composition of built-in GPU primitives *or* a WGSL/GLSL
snippet pair, and hover/a11y descriptors. This module ships the first and the
composition half of the second, and deliberately not the shader half.

The reason is not schedule. A plugin that composes built-in marks cannot draw
anything the engine could not already draw, so its traces move through the
paths that already exist: LOD and decimation (§28), picking and hover, the wire
protocol's f32 discipline (§29), and every export path including the two that
have no browser. It reuses them rather than reimplementing them. A plugin
carrying its own shader would reuse none of that, so shaders are a second
system and can wait until something real needs one.

    import numpy as np
    import xy

    def _calc(columns):
        low, high = columns["low"], columns["high"]
        return {**columns, "mid": (low + high) / 2.0}

    def _build(ctx):
        return [
            xy.segments(
                x0=ctx.columns["t"], x1=ctx.columns["t"],
                y0=ctx.columns["low"], y1=ctx.columns["high"],
                style=ctx.style,
            ),
            xy.scatter(x=ctx.columns["t"], y=ctx.columns["mid"], size=4),
        ]

    xy.register_mark(
        xy.MarkPlugin(name="hilo", columns=("t", "low", "high"), calc=_calc, build=_build)
    )

    chart = xy.chart(xy.mark("hilo", t=ts, low=lows, high=highs, data=frame))

A plugin's `build` returns built-in `Mark` objects and nothing else; it never
sees the `Figure`, the trace list, or the column store. `tests/test_mark_plugins.py`
holds that boundary: the composed marks go through the same appliers, the same
axis assignment, and the same post-processing as marks written by hand, because
they *are* marks written by hand — just written by someone else's function.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import cycle at runtime
    from .components import Mark


@dataclass(frozen=True)
class MarkContext:
    """Everything a plugin's `build` is allowed to see.

    Deliberately not a `Figure`: a plugin composes marks, it does not drive the
    engine. `columns` holds the plugin's declared columns after `calc` has run,
    with any string values already resolved against the chart's `data=`.
    """

    columns: Mapping[str, Any]
    options: Mapping[str, Any]
    name: str | None = None
    style: Mapping[str, Any] = field(default_factory=dict)
    class_name: str | None = None


@dataclass(frozen=True)
class MarkPlugin:
    """A mark kind contributed from outside the core.

    `columns` names the fields `xy.mark(...)` will resolve against `data=`;
    everything else a caller passes lands in `MarkContext.options` untouched.
    `calc` runs once over the resolved columns and returns the columns `build`
    sees — this is §24's "calc function over columns → columns", running in
    Python today rather than in the worker.
    """

    name: str
    build: Callable[[MarkContext], "Sequence[Mark]"]
    columns: tuple[str, ...] = ()
    calc: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None
    doc: str = ""


#: `xy.mark()` binds these itself, so a column with one of these names could
#: never be passed: the caller's value would land on the `mark()` parameter and
#: the column would silently resolve to None. Rejecting the schema at
#: registration turns a confusing runtime result into an import-time error.
_MARK_CONTROL_FIELDS: frozenset[str] = frozenset(
    {"kind", "data", "name", "style", "class_name", "key", "animation", "x_axis", "y_axis"}
)

_REGISTRY: dict[str, MarkPlugin] = {}


def register_mark(plugin: MarkPlugin, *, replace: bool = False) -> MarkPlugin:
    """Register a mark plugin under its name.

    Refuses to shadow a built-in kind, and refuses to silently replace another
    plugin: two libraries registering `"candlestick"` is a conflict their user
    needs to know about, not a race the import order settles.
    """
    from .components import _MARK_APPLIERS

    if not isinstance(plugin, MarkPlugin):
        raise TypeError(f"register_mark expects a MarkPlugin, got {type(plugin).__name__}")
    if not plugin.name or not plugin.name.isidentifier():
        raise ValueError(f"mark plugin name must be an identifier, got {plugin.name!r}")
    if plugin.name in _MARK_APPLIERS:
        raise ValueError(f"{plugin.name!r} is a built-in mark kind and cannot be replaced")
    if plugin.name in _REGISTRY and not replace:
        raise ValueError(
            f"mark plugin {plugin.name!r} is already registered; "
            "pass replace=True if that is intended"
        )
    if not callable(plugin.build):
        raise TypeError(f"mark plugin {plugin.name!r} build must be callable")
    if plugin.calc is not None and not callable(plugin.calc):
        raise TypeError(f"mark plugin {plugin.name!r} calc must be callable or None")
    duplicates = sorted({c for c in plugin.columns if plugin.columns.count(c) > 1})
    if duplicates:
        raise ValueError(f"mark plugin {plugin.name!r} repeats column(s) {duplicates}")
    reserved = sorted(set(plugin.columns) & _MARK_CONTROL_FIELDS)
    if reserved:
        raise ValueError(
            f"mark plugin {plugin.name!r} declares column(s) {reserved}, which "
            f"xy.mark() binds itself; rename them"
        )
    _REGISTRY[plugin.name] = plugin
    return plugin


def unregister_mark(name: str) -> None:
    """Remove a registered plugin. Unknown names are a no-op."""
    _REGISTRY.pop(name, None)


def registered_marks() -> tuple[str, ...]:
    """Names of every registered mark plugin, sorted."""
    return tuple(sorted(_REGISTRY))


def get_mark_plugin(name: str) -> MarkPlugin | None:
    """The registered plugin for `name`, or None if nothing claims it."""
    return _REGISTRY.get(name)


__all__ = [
    "MarkContext",
    "MarkPlugin",
    "get_mark_plugin",
    "register_mark",
    "registered_marks",
    "unregister_mark",
]
