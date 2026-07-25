"""Public annotations must resolve at runtime.

`typing.get_type_hints()` is how doc tools, runtime validators, and REPL
helpers introspect the shim; a name imported only under TYPE_CHECKING but
referenced by a public signature raises NameError there (PR #57 review).
"""

from __future__ import annotations

import inspect
import typing

import xy.pyplot as plt
from xy import components
from xy.pyplot import Line2D


def test_every_exported_pyplot_callable_has_resolvable_annotations() -> None:
    for name in plt.__all__:
        obj = getattr(plt, name)
        if callable(obj) and not isinstance(obj, type):
            typing.get_type_hints(obj)  # NameError here is a regression


def test_public_axes_methods_have_resolvable_annotations() -> None:
    for name, member in inspect.getmembers(plt.Axes, inspect.isfunction):
        if not name.startswith("_"):
            typing.get_type_hints(member)


def test_component_factories_have_resolvable_annotations() -> None:
    for name, member in vars(components).items():
        if not name.startswith("_") and inspect.isfunction(member):
            typing.get_type_hints(member)


def test_findobj_returns_axes_and_artists() -> None:
    fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [1, 2])
    found = plt.findobj(fig)
    assert ax in found
    assert line in found
    assert plt.findobj(fig, match=Line2D) == [line]
    assert plt.findobj(fig, match=lambda a: a is line) == [line]
    plt.close("all")
