"""Machine-checkable records about XY's styling surface.

`capabilities` is the inventory: what can be styled, in which renderer, and
how far it travels. It is imported by the docs generator and pinned by
`tests/test_capability_registry.py`, so a claim about customization can be
checked against it rather than against a reading of `styles.py`.

`preflight` applies that inventory to one concrete chart and export target:
`chart.style_compatibility_report()` routes every declared style and names
what would not survive, before any bytes exist.

`resolved` is the renderer-neutral styling IR those two converge on: the
versioned, interned `ResolvedStyleSnapshot` of concrete values that every
resolver produces and every renderer consumes.

`cascade` is the mount-free resolver over the optional native extension:
classes and author CSS cascaded to concrete values with no browser.

Submodules resolve lazily (PEP 562): `capabilities` reaches the writers'
constants and, through them, the native library — so importing this package
costs nothing until a submodule is actually used. That keeps the documented
zero-import guarantee of the `legacy` export path true even for code that
imports `xy.styling` itself.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["capabilities", "cascade", "preflight", "resolved"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        module = importlib.import_module(f".{name}", __name__)
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
