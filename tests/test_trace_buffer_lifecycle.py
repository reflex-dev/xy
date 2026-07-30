"""The client must delete every GL buffer a trace build can create.

Repeated data updates rebuild GPU traces: `_appendTraceInPlace` bails out, the
old record is torn down, and `_buildTrace` makes a new one. Teardown used a
hand-kept list of geometry buffer names, so the style, direct-rgba colour,
stroke, corner-radius, LOD-blend and dashed-line-length buffers were orphaned on
every update and the leak grew without bound.

The fix is one shared list (`TRACE_GPU_BUFFERS`, js/src/00_header.ts) read by all
three teardown paths. This module pins the list against the build paths, so a new
channel buffer cannot reintroduce the leak by simply not being mentioned.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_SRC = ROOT / "js/src"

# `g.styleBuf = ...`, `d.dBuf = gl.createBuffer()`, `s._lenBuf = this._upload(x)`
# — an assignment that puts a buffer handle on a trace-shaped record. The `._`
# prefix form is included: private derived buffers leak exactly like public ones.
_BUFFER_ASSIGNMENT = re.compile(r"\b\w+\.(_?[A-Za-z][A-Za-z0-9]*Buf)\s*=(?!=)")


def _trace_gpu_buffers() -> list[str]:
    source = (JS_SRC / "00_header.ts").read_text(encoding="utf-8")
    block = source.split("export const TRACE_GPU_BUFFERS = [", 1)[1].split("];", 1)[0]
    return re.findall(r'"([^"]+)"', block)


def _assigned_buffer_fields() -> dict[str, set[str]]:
    """Buffer field name -> the modules that assign it."""
    assigned: dict[str, set[str]] = {}
    for path in sorted(JS_SRC.glob("*.ts")):
        for name in _BUFFER_ASSIGNMENT.findall(path.read_text(encoding="utf-8")):
            assigned.setdefault(name, set()).add(path.name)
    return assigned


def test_trace_teardown_deletes_every_gpu_buffer() -> None:
    listed = _trace_gpu_buffers()
    assert listed, "TRACE_GPU_BUFFERS could not be parsed out of 00_header.ts"
    assert len(listed) == len(set(listed)), "TRACE_GPU_BUFFERS has duplicate names"

    assigned = _assigned_buffer_fields()
    missing = {name: sorted(mods) for name, mods in assigned.items() if name not in listed}
    assert not missing, (
        "these GL buffer fields are created but never deleted — add them to "
        f"TRACE_GPU_BUFFERS in js/src/00_header.ts: {missing}"
    )


def test_every_teardown_path_reads_the_shared_buffer_list() -> None:
    """No path may keep its own subset; that is how the leak started."""
    chartview = (JS_SRC / "50_chartview.ts").read_text(encoding="utf-8")
    lod = (JS_SRC / "45_lod.ts").read_text(encoding="utf-8")

    # The live trace, its drill window, and a sample overlay.
    assert "this._deleteBuffers(g, TRACE_GPU_BUFFERS);" in chartview
    assert "this._deleteBuffers(g.drill, TRACE_GPU_BUFFERS);" in chartview
    assert "this._deleteBuffers(s, TRACE_GPU_BUFFERS);" in chartview
    assert "view._deleteBuffers(d, TRACE_GPU_BUFFERS);" in lod

    # The retained M4 overview owns only its geometry; its channel buffers are
    # aliases of the live trace's and are deleted exactly once, above.
    assert 'this._deleteBuffers(g._homeDecimated, ["xBuf", "yBuf", "baseBuf"]);' in chartview
