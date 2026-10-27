"""Machine-checkable records about XY's styling surface.

`capabilities` is the one that matters: what can be styled, in which renderer,
and how far it travels. It is imported by the docs generator and pinned by
`tests/test_capability_registry.py`, so a claim about customization can be
checked against it rather than against a reading of `styles.py`.
"""

from __future__ import annotations

from . import capabilities

__all__ = ["capabilities"]
