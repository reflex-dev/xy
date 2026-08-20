"""The linear-axis fold: high-magnitude precision and per-column map pairing.

Issue #487 — a millisecond-epoch x axis renders as stepped columns with gaps —
is a numeric property of the vertex transform, so the first test here is the
arithmetic itself, in f32, with no browser. The rest pin the structural
invariants the fix depends on: one map per *encoded column*, never one per
axis, and one place that builds them (§4/§16).
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

JS = Path(__file__).parents[1] / "js" / "src"
GL_SRC = (JS / "40_gl.ts").read_text(encoding="utf-8")
VIEW_SRC = (JS / "50_chartview.ts").read_text(encoding="utf-8")

# 2024-06-01T00:00:00Z in ms since the epoch, four hours of it, 30k samples:
# the reporter's shape (hundreds of samples a second over many hours).
T0 = 1_717_200_000_000.0
SPAN_MS = 4 * 60 * 60 * 1000.0
N = 30_000
PLOT_PX = 820


def f32(value: float) -> float:
    """Round through a 32-bit float, the way a GPU uniform or attribute does."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _series() -> tuple[list[float], float, float, float, float]:
    step = SPAN_MS / (N - 1)
    values = [T0 + i * step for i in range(N)]
    offset = T0 + SPAN_MS / 2  # Column.suggest_offset: the domain midpoint
    scale = 1.0
    return values, offset, scale, T0, T0 + SPAN_MS


def _columns(clips: list[float]) -> int:
    """Distinct pixel columns a run of clip-space x coordinates lands on."""
    return len({round((clip + 1) / 2 * PLOT_PX) for clip in clips})


def _folded_clips() -> list[float]:
    """`_map` + `xyMap` mode 0: fold on the CPU in f64, apply to encoded f32."""
    values, offset, scale, lo, hi = _series()
    data_mul = 2 / (hi - lo)
    mul = data_mul / scale
    shift = f32(((lo + hi) / 2 - offset) * scale)
    add = (offset + shift / scale - lo) * data_mul - 1
    return [f32(f32(f32((v - offset) * scale) - shift) * f32(mul) + f32(add)) for v in values]


def _decoded_clips() -> list[float]:
    """The pre-fix path: rebuild the absolute coordinate in f32, then map."""
    values, offset, scale, lo, hi = _series()
    mul = f32(2 / (hi - lo))
    add = f32(-1 - lo * (2 / (hi - lo)))
    out = []
    for v in values:
        encoded = f32((v - offset) * scale)
        decoded = f32(f32(encoded / f32(scale)) + f32(offset))
        out.append(f32(f32(decoded * mul) + add))
    return out


def test_decoding_a_millisecond_epoch_in_f32_quantises_the_series() -> None:
    """The bug, stated as arithmetic: f32 cannot hold 1.7e12 to the millisecond.

    Its quantum there is 2**17 ms, so four hours of samples can only occupy
    SPAN / 2**17 distinct positions however many points are shipped.
    """
    reachable = SPAN_MS / 2**17
    assert _columns(_decoded_clips()) == pytest.approx(reachable, rel=0.15)


def test_the_linear_fold_keeps_the_full_intra_view_spread() -> None:
    """Folding the offset in f64 leaves the encoded value's own precision."""
    assert _columns(_folded_clips()) == PLOT_PX + 1


def test_the_fold_lands_the_endpoints_on_the_view_edges() -> None:
    """Precision is worthless if the transform itself has drifted."""
    clips = _folded_clips()
    assert clips[0] == pytest.approx(-1.0, abs=1e-5)
    assert clips[-1] == pytest.approx(1.0, abs=1e-5)


def test_every_shader_map_is_paired_with_its_own_columns_meta() -> None:
    """A map folded for one column is a different transform, not a rounding
    difference, so `xyMap` must never receive a sibling column's map: the
    stems of the map and meta arguments have to match."""
    calls = re.findall(r"xyMap\(\s*([\w.]+),\s*([\w.]+),\s*([\w.]+),", GL_SRC)
    assert calls, "no xyMap call sites found — the extraction regex is broken"
    mismatched = [
        (mapped, meta)
        for _, mapped, meta in calls
        if not (mapped.endswith("map") and meta.endswith("meta") and mapped[:-3] == meta[:-4])
    ]
    assert mismatched == [], f"xyMap called with a map from another column: {mismatched}"


def test_every_map_uniform_carries_the_four_folded_components() -> None:
    """(mul, add, shift, dataMul) — a vec2 declaration means a stale shader."""
    narrow = re.findall(r"uniform\s+vec[23]\s+(u_\w*map)\b", GL_SRC)
    assert narrow == [], f"map uniforms must be vec4: {narrow}"


def test_maps_are_built_in_exactly_one_place() -> None:
    """`_setAxisUniforms` writes the map beside the meta it was folded from.

    Any other caller of `_map` is free to pair them wrongly, which is the
    regression this whole module exists to prevent.
    """
    assert VIEW_SRC.count("this._map(") == 1, "_map must have exactly one caller"
    body = VIEW_SRC.split("_setAxisUniforms(prog, prefix, meta, axisId, range = null) {", 1)[1]
    body = body.split("\n  }\n", 1)[0]
    assert "this._map(meta, range[0], range[1], axisId)" in body
    assert "uniform4f(u(`${prefix}map`)" in body
    assert not re.search(r'uniform[234]f\(u\("u_\w*map"\)', VIEW_SRC), (
        "map uniforms must only be written by _setAxisUniforms"
    )


def test_the_fold_floors_a_degenerate_encode_scale() -> None:
    """`xyDecode` guards with `max(abs(meta.y), 1e-30)`; the CPU fold divides
    by the same scale and must floor it identically, or a zero-scale column
    yields an infinite slope and NaN clip positions."""
    body = VIEW_SRC.split("_map(meta, lo, hi, axisId = null) {", 1)[1].split("\n  }\n", 1)[0]
    assert "1e-30" in body, "the encode-scale floor is missing from the linear fold"
    # And the constants are validated as f32, since that is how they travel to
    # the GPU: an f64-finite slope that overflows on upload is still Infinity
    # in the shader, and `encoded * Infinity` rasterizes as NaN.
    assert "Number.isFinite(Math.fround(mul))" in body
    assert "Number.isFinite(Math.fround(add))" in body
