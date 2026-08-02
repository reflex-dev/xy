"""XY Terminal: a deterministic multi-workspace Reflex example.

Run from ``examples/reflex`` with ``uv run reflex run``.  The page uses no
runtime network services or API keys; every market value is simulated.
"""

from __future__ import annotations

import reflex as rx

from .components import index
from .state import Demo, TerminalState

app = rx.App()
app.add_page(index, title="XY Terminal · Simulated Markets")

__all__ = ["Demo", "TerminalState", "app", "index"]
