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

# Selection lives in figure.py (it's the on_select payload and has no widget
# dependency); re-exported here for backward compatibility.
from .figure import Selection
from .interaction import _integer_id

if TYPE_CHECKING:
    from .figure import Figure

_STATIC = pathlib.Path(__file__).parent / "static"

__all__ = ["FigureWidget", "Selection", "bundled_js"]


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

    def __init__(
        self,
        figure: "Figure",
        *,
        on_hover: Any = None,
        on_select: Any = None,
        **kwargs: Any,
    ) -> None:
        self._figure = figure
        self._on_hover = on_hover
        self._on_select = on_select
        spec, blob = figure.build_payload()
        super().__init__(spec=spec, buffers=blob, **kwargs)
        self.on_msg(self._on_custom_msg)

    def append(self, trace_id: int, x: Any, y: Any, *, color: Any = None, size: Any = None) -> None:
        """Streaming append: extend a trace's data and push the refresh to the
        client. Also refreshes the synced spec/buffers traits so a re-rendered
        output (notebook reopen) shows the streamed state, not the initial one."""
        msg, buffers = self._figure.append(trace_id, x, y, color=color, size=size)
        self.spec = msg["spec"]
        self.buffers = buffers[0]
        self.send(msg, buffers=buffers)

    def _on_custom_msg(self, widget: Any, content: Any, msg_buffers: Any) -> None:
        if not isinstance(content, dict):
            return
        kind = content.get("type")
        if kind == "view":
            # Zoom/pan crossed what the shipped decimation can serve: recompute
            # for the visible window only (§28), stale-while-revalidate on the
            # client (§17 — it keeps drawing the old tier until this arrives).
            seq = content.get("seq")
            try:
                x0 = float(content["x0"])
                x1 = float(content["x1"])
                if not x1 > x0:
                    return
                update, buffers = self._figure.decimate_view(
                    x0,
                    x1,
                    content.get("px", 2048),
                )
            except (KeyError, TypeError, ValueError):
                return
            if update["traces"]:
                self.send({"type": "tier_update", "seq": seq, **update}, buffers=buffers)
        elif kind == "density_view":
            # Tier-2 scatter panned/zoomed: re-bin the visible window (§5).
            seq = content.get("seq")
            try:
                update, buffers = self._figure.density_view(
                    content["trace"],
                    content["x0"],
                    content["x1"],
                    content["y0"],
                    content["y1"],
                    content.get("w", 512),
                    content.get("h", 384),
                )
            except (KeyError, TypeError, ValueError, IndexError):
                return
            if update["traces"]:
                self.send({"type": "density_update", "seq": seq, **update}, buffers=buffers)
        elif kind == "pick":
            # Hover/click drill: exact f64 row from canonical (§16/§17). The
            # client's drill_seq rejects picks that raced a subset swap.
            dseq = content.get("drill_seq")
            try:
                trace_id = _integer_id(content.get("trace", -1), "trace")
                index = _integer_id(content.get("index", -1), "index")
                drill_seq = None if dseq is None else _integer_id(dseq, "drill_seq")
                row = self._figure.pick(
                    trace_id,
                    index,
                    drill_seq,
                )
            except (TypeError, ValueError):
                return
            self.send({"type": "pick_result", "seq": content.get("seq"), "row": row})
            if row is not None and self._on_hover is not None:
                self._on_hover(row)
        elif kind == "select":
            # Box-select → range predicate (§34 Tier A). Ship a selection mask
            # per trace so the client dims unselected marks; call on_select with
            # the resolved indices (Arrow-slice-shaped, not JSON — §34 API note).
            try:
                sel = self._figure.select_range(
                    content["x0"],
                    content["x1"],
                    content["y0"],
                    content["y1"],
                )
            except (KeyError, TypeError, ValueError):
                return
            traces = []
            buffers = []
            total = 0
            for tid, idx in sel.items():
                # The wire mask speaks shipped-vertex positions; the Selection
                # callback below keeps canonical rows (§34 — callbacks get real
                # data, the GPU gets its own coordinate space).
                wire_idx = self._figure.to_shipped_indices(tid, idx)
                traces.append(
                    {
                        "id": tid,
                        "count": int(len(wire_idx)),
                        "buf": len(buffers),
                        # Which drilled subset this mask speaks for; the client
                        # drops it if its buffers have moved on (§17).
                        "drill_seq": self._figure.traces[tid].drill_seq,
                    }
                )
                buffers.append(wire_idx.tobytes())
                total += len(idx)
            self.send({"type": "selection", "traces": traces, "total": total}, buffers=buffers)
            if self._on_select is not None:
                self._on_select(Selection(self._figure, sel))
        elif kind == "select_clear":
            self.send({"type": "selection", "traces": [], "total": 0})
            if self._on_select is not None:
                self._on_select(Selection(self._figure, {}))
