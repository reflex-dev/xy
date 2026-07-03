"""anywidget integration (§33.3): one widget implementation covers Jupyter,
JupyterLab, VS Code, Colab, and Marimo, with a binary comm channel — spec as
JSON, data as raw buffers, never base64/JSON numbers (§29 Jupyter row).

The JS render client ships inside the wheel as a static asset — versioned,
no CDN (§33.2, airgapped notebooks).
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING, Any

import anywidget
import traitlets

if TYPE_CHECKING:
    from .figure import Figure

_STATIC = pathlib.Path(__file__).parent / "static"


def bundled_js(which: str = "widget") -> str:
    """Read a bundled client build ("widget" ESM or "standalone" IIFE)."""
    name = "index.js" if which == "widget" else "standalone.js"
    path = _STATIC / name
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing — the JS client was not bundled into this install. "
            "Dev checkout: run `npm run build` in js/."
        )
    return path.read_text(encoding="utf-8")


class FigureWidget(anywidget.AnyWidget):
    _esm = _STATIC / "index.js"

    # Data-less spec (§9) — tiny JSON, sync'd as a trait.
    spec = traitlets.Dict().tag(sync=True)
    # Encoded columns — one binary blob, transported as a raw buffer by the
    # widget protocol (ipywidgets serializes Bytes traits as binary buffers,
    # never JSON).
    buffers = traitlets.Bytes().tag(sync=True)

    def __init__(self, figure: "Figure", **kwargs: Any) -> None:
        self._figure = figure
        spec, blob = figure.build_payload()
        super().__init__(spec=spec, buffers=blob, **kwargs)
        self.on_msg(self._on_custom_msg)

    def _on_custom_msg(self, widget: Any, content: Any, msg_buffers: Any) -> None:
        if not isinstance(content, dict):
            return
        if content.get("type") == "view":
            # Zoom/pan crossed what the shipped decimation can serve: recompute
            # for the visible window only (§28), stale-while-revalidate on the
            # client (§17 — it keeps drawing the old tier until this arrives).
            x0 = float(content["x0"])
            x1 = float(content["x1"])
            px = int(content.get("px", 2048))
            seq = content.get("seq")
            if not x1 > x0:
                return
            update, buffers = self._figure.decimate_view(x0, x1, px)
            if update["traces"]:
                self.send(
                    {"type": "tier_update", "seq": seq, **update},
                    buffers=buffers,
                )
