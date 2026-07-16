"""Frontend assets for the Reflex component.

Two files ship here:

- ``XYChart.jsx`` — the React wrapper (multiplexes the `/_xy` namespace onto
  the app's existing websocket and drives ChartView).
- ``xy_client.js`` — a byte-exact copy of the render client
  (``python/xy/static/index.js``); ``node js/build.mjs`` regenerates both
  and ``tests/reflex_xy/test_assets.py`` fails on drift.

`register()` is deliberately lazy (called from the component factory, not at
import): ``rx.asset(shared=True)`` symlinks into ``Path.cwd()/assets``, which
only makes sense while compiling an actual Reflex app. It must be called
from *this* module so the files land in one directory and the wrapper's
relative ``./xy_client.js`` import resolves.
"""

from __future__ import annotations

WRAPPER_TAG = "XYChart"


def register() -> str:
    """Symlink both assets into the compiling app; return the wrapper's
    importable module path (``$/public/external/reflex_xy/assets/...``)."""
    import reflex as rx

    rx.asset("xy_client.js", shared=True)
    return rx.asset("XYChart.jsx", shared=True).importable_path
