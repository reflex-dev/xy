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


class Selection:
    """The payload handed to an `on_select` callback (§34). Holds the selected
    row indices per trace and lends convenient access to the underlying data —
    callbacks receive real arrays, never JSON."""

    def __init__(self, figure: "Figure", per_trace: dict) -> None:
        self._figure = figure
        self.per_trace = per_trace  # {trace_id: np.ndarray[uint32]}

    @property
    def index(self):  # noqa: ANN201
        """Concatenated selected indices across all traces (single-trace charts
        are the common case, where this is just that trace's indices)."""
        import numpy as np

        arrs = list(self.per_trace.values())
        return np.concatenate(arrs) if arrs else np.empty(0, dtype="uint32")

    def __len__(self) -> int:
        return int(sum(len(v) for v in self.per_trace.values()))

    def xy(self, trace_id: int = 0):  # noqa: ANN201
        """(x, y) f64 arrays for the selected points of a trace (from canonical)."""
        idx = self.per_trace.get(trace_id)
        t = self._figure.traces[trace_id]
        if idx is None:
            import numpy as np

            return np.empty(0), np.empty(0)
        return t.x.values[idx], t.y.values[idx]


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

    def _on_custom_msg(self, widget: Any, content: Any, msg_buffers: Any) -> None:
        if not isinstance(content, dict):
            return
        kind = content.get("type")
        if kind == "view":
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
                self.send({"type": "tier_update", "seq": seq, **update}, buffers=buffers)
        elif kind == "density_view":
            # Tier-2 scatter panned/zoomed: re-bin the visible window (§5).
            seq = content.get("seq")
            try:
                update, buffers = self._figure.density_view(
                    int(content["trace"]),
                    float(content["x0"]), float(content["x1"]),
                    float(content["y0"]), float(content["y1"]),
                    int(content.get("w", 512)), int(content.get("h", 384)),
                )
            except (KeyError, ValueError, IndexError):
                return
            if update["traces"]:
                self.send({"type": "density_update", "seq": seq, **update}, buffers=buffers)
        elif kind == "pick":
            # Hover/click drill: exact f64 row from canonical (§16/§17).
            row = self._figure.pick(int(content.get("trace", -1)), int(content.get("index", -1)))
            self.send({"type": "pick_result", "seq": content.get("seq"), "row": row})
            if row is not None and self._on_hover is not None:
                self._on_hover(row)
        elif kind == "select":
            # Box-select → range predicate (§34 Tier A). Ship a selection mask
            # per trace so the client dims unselected marks; call on_select with
            # the resolved indices (Arrow-slice-shaped, not JSON — §34 API note).
            try:
                sel = self._figure.select_range(
                    float(content["x0"]), float(content["x1"]),
                    float(content["y0"]), float(content["y1"]),
                )
            except (KeyError, ValueError):
                return
            traces = []
            buffers = []
            total = 0
            for tid, idx in sel.items():
                # The wire mask speaks shipped-vertex positions; the Selection
                # callback below keeps canonical rows (§34 — callbacks get real
                # data, the GPU gets its own coordinate space).
                wire_idx = self._figure.to_shipped_indices(tid, idx)
                traces.append({"id": tid, "count": int(len(wire_idx)), "buf": len(buffers)})
                buffers.append(wire_idx.tobytes())
                total += len(idx)
            self.send({"type": "selection", "traces": traces, "total": total}, buffers=buffers)
            if self._on_select is not None:
                self._on_select(Selection(self._figure, sel))
        elif kind == "select_clear":
            self.send({"type": "selection", "traces": [], "total": 0})
            if self._on_select is not None:
                self._on_select(Selection(self._figure, {}))
