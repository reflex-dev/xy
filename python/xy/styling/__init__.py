"""Machine-checkable records about XY's styling surface.

`capabilities` is the inventory: what can be styled, in which renderer, and
how far it travels. It is imported by the docs generator and pinned by
`tests/test_capability_registry.py`, so a claim about customization can be
checked against it rather than against a reading of `styles.py`.

`preflight` applies that inventory to one concrete chart and export target:
`chart.style_compatibility_report()` routes every declared style and names
what would not survive, before any bytes exist.
"""

from __future__ import annotations

from . import capabilities, preflight

__all__ = ["capabilities", "preflight"]
