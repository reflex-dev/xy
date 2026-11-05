"""The linear-axis fold: high-magnitude precision and per-column map pairing.

Issue #487 — a millisecond-epoch x axis renders as stepped columns with gaps —
is a numeric property of the vertex transform, so most of this module drives
the *shipped* `_map` out of the built ES bundle through node and applies the
shader's own one-line affine in f32 on top of the constants it returns. That
keeps the assertions behavioural: they survive any reformatting of the client
and fail on a real change of transform.

The remaining checks are whitespace-tolerant regexes over the GLSL, for the two
invariants a numeric test cannot see: that every `xyMap` call takes the map and
the meta of the *same* encoded column, and that a bar's data-space width is
transformed rather than scaled on a non-affine axis (§4/§16).

Run `node js/build.mjs` once per checkout so the bundle exists.
"""

from __future__ import annotations

import json
import os
import re
import struct
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "python" / "xy" / "static" / "index.js"
GL_SRC = (ROOT / "js" / "src" / "40_gl.ts").read_text(encoding="utf-8")
VIEW_SRC = (ROOT / "js" / "src" / "50_chartview.ts").read_text(encoding="utf-8")

# 2024-06-01T00:00:00Z in ms since the epoch, four hours of it, 30k samples:
# the reporter's shape (hundreds of samples a second over many hours).
T0 = 1_717_200_000_000.0
SPAN_MS = 4 * 60 * 60 * 1000.0
N = 30_000
PLOT_PX = 820


def f32(value: float) -> float:
    """Round through a 32-bit float, the way a GPU uniform or attribute does."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def js_maps(cases: list[dict]) -> list[dict]:
    """Call the shipped `ChartView.prototype._map` on each case.

    `_map` reads only `_axis`/`_axisMode`/`_axisCoord`, all of which are pure
    apart from `this.axes`, so a bare context is enough — no DOM, no WebGL.

    Only the callers of this helper need the bundle; the GLSL checks below read
    source, so the skip belongs here rather than on the module.
    """
    if not BUNDLE.exists():
        pytest.skip("run `node js/build.mjs` to build the client bundle")
    script = """
import { ChartView } from "./python/xy/static/index.js";
const proto = ChartView.prototype;
const out = JSON.parse(process.env.XY_CASES).map((c) => {
  const ctx = {
    axes: { x: c.axis || {} },
    _axis: proto._axis,
    _axisMode: proto._axisMode,
    _axisCoord: proto._axisCoord,
    _axisConstant: proto._axisConstant,
  };
  return proto._map.call(ctx, c.meta, c.lo, c.hi, "x");
});
process.stdout.write(JSON.stringify(out));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
        # Inherit the environment: node needs whatever PATH, HOME, NODE_OPTIONS
        # and NODE_PATH the runner set, and a hand-built env silently breaks on
        # any machine that installs node somewhere else.
        env={**os.environ, "XY_CASES": json.dumps(cases)},
    )
    return json.loads(completed.stdout)


def clip(encoded: float, m: dict) -> float:
    """`xyMap` mode 0, in f32: `(encoded - map.z) * map.x + map.y`."""
    return f32(f32(f32(encoded) - f32(m["shift"])) * f32(m["mul"]) + f32(m["add"]))


def columns(clips: list[float]) -> int:
    """Distinct pixel columns a run of clip-space x coordinates lands on."""
    return len({round((c + 1) / 2 * PLOT_PX) for c in clips})


def epoch_series() -> tuple[list[float], float, float, float]:
    step = SPAN_MS / (N - 1)
    values = [T0 + i * step for i in range(N)]
    offset = T0 + SPAN_MS / 2  # Column.suggest_offset: the domain midpoint
    return values, offset, T0, T0 + SPAN_MS


def test_decoding_a_millisecond_epoch_in_f32_quantises_the_series() -> None:
    """The bug, stated as arithmetic: f32 cannot hold 1.7e12 to the millisecond.

    Its quantum there is 2**17 ms, so four hours of samples can only occupy
    SPAN / 2**17 distinct positions however many points are shipped. This is
    the transform the client used to apply, written out; nothing calls it now.
    """
    values, offset, lo, hi = epoch_series()
    mul, add = f32(2 / (hi - lo)), f32(-1 - lo * (2 / (hi - lo)))
    decoded = [f32(f32(f32(f32(v - offset) + f32(offset)) * mul) + add) for v in values]
    assert columns(decoded) == pytest.approx(SPAN_MS / 2**17, rel=0.15)


def test_the_shipped_fold_keeps_the_full_intra_view_spread() -> None:
    """Folding the offset in f64 leaves the encoded value's own precision."""
    values, offset, lo, hi = epoch_series()
    (m,) = js_maps([{"meta": {"offset": offset, "scale": 1.0}, "lo": lo, "hi": hi}])
    clips = [clip(v - offset, m) for v in values]
    assert columns(clips) == PLOT_PX + 1
    # Precision is worthless if the transform itself has drifted.
    assert clips[0] == pytest.approx(-1.0, abs=1e-5)
    assert clips[-1] == pytest.approx(1.0, abs=1e-5)


def test_a_zero_encode_scale_pins_the_column_to_its_offset() -> None:
    """Every encoded value is 0, so the honest picture is "all on the offset".

    Dividing by that scale instead hands the shader an infinite slope, and
    `encoded * Infinity` rasterizes as NaN — the trace vanishes.
    """
    (m,) = js_maps([{"meta": {"offset": 400.0, "scale": 0.0}, "lo": 0.0, "hi": 1000.0}])
    assert m["mul"] == 0
    assert clip(0.0, m) == pytest.approx(400.0 / 1000.0 * 2 - 1, abs=1e-6)


def test_a_tiny_but_finite_encode_scale_is_used_as_shipped() -> None:
    """An enormous finite domain gets a legitimately tiny encode scale.

    The fold divides in f64, so it must use the very scale the vertex buffer
    was encoded with. Flooring |scale| at some epsilon would rescale the whole
    trace — at 1e-30 this case would land its endpoints at ±0.1, not ±1.
    """
    scale, offset, half = 1e-31, 5e68, 5e68
    (m,) = js_maps([{"meta": {"offset": offset, "scale": scale}, "lo": 0.0, "hi": 2 * half}])
    assert clip((0.0 - offset) * scale, m) == pytest.approx(-1.0, abs=1e-3)
    assert clip((2 * half - offset) * scale, m) == pytest.approx(1.0, abs=1e-3)


def test_a_non_affine_axis_reports_no_data_space_slope() -> None:
    """There is no constant clip-per-data-unit on log/symlog, so `dataMul` is
    0 and a caller needing a data-space span must transform both edges."""
    maps = js_maps(
        [
            {
                "axis": {"scale": "log"},
                "meta": {"offset": 0.0, "scale": 1.0},
                "lo": 1.0,
                "hi": 1000.0,
            },
            {
                "axis": {"scale": "symlog", "constant": 1},
                "meta": {"offset": 0.0, "scale": 1.0},
                "lo": -100.0,
                "hi": 100.0,
            },
        ]
    )
    assert [m["dataMul"] for m in maps] == [0, 0]
    assert [m["shift"] for m in maps] == [0, 0]
    # A linear axis does report one: clip units per data unit over the window.
    (linear,) = js_maps([{"meta": {"offset": 0.0, "scale": 1.0}, "lo": 0.0, "hi": 1000.0}])
    assert linear["dataMul"] == pytest.approx(2 / 1000)


def test_an_unrepresentable_constant_maps_off_screen() -> None:
    """Every exit is validated in f32, including the zero-scale one: an f64
    finite `add` that overflows on upload is still an Infinity in the shader."""
    (m,) = js_maps([{"meta": {"offset": 1e30, "scale": 0.0}, "lo": 0.0, "hi": 1e-12}])
    assert (m["mul"], m["add"], m["dataMul"]) == (0, -2, 0)


def test_a_window_too_narrow_for_an_f32_slope_only_loses_the_width() -> None:
    """`dataMul` feeds nothing but a bar's data-space width, so an overflow
    there zeroes that alone — positions, which never read it, keep working."""
    (m,) = js_maps([{"meta": {"offset": 5e-41, "scale": 1e3}, "lo": 0.0, "hi": 1e-40}])
    assert m["dataMul"] == 0, "an f32-infinite data slope must not reach BAR_VS"
    assert m["mul"] != 0 and m["add"] == pytest.approx(0.0, abs=1e-6)
    assert clip((0.0 - 5e-41) * 1e3, m) == pytest.approx(-1.0, abs=1e-3)


def test_a_degenerate_window_maps_off_screen() -> None:
    """`mul` 0 with `add` -2 parks the mark outside clip space, which is what
    every unrepresentable transform has always returned."""
    maps = js_maps(
        [
            {"meta": {"offset": 0.0, "scale": 1.0}, "lo": 5.0, "hi": 5.0},
            {"axis": {"scale": "log"}, "meta": {"offset": 0.0, "scale": 1.0}, "lo": 0.0, "hi": 0.0},
        ]
    )
    for m in maps:
        assert (m["mul"], m["add"]) == (0, -2)


def test_every_shader_map_is_paired_with_its_own_columns_meta() -> None:
    """A map folded for one column is a different transform, not a rounding
    difference, so `xyMap` must never receive a sibling column's map: the
    stems of the map and meta arguments have to match."""
    calls = re.findall(r"xyMap\(\s*([\w.]+),\s*([\w.]+),\s*([\w.]+)\s*,", GL_SRC)
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


def test_a_bar_transforms_both_edges_on_a_non_affine_axis() -> None:
    """A bar's width is a data-space span. Scaling it by a coordinate-space
    slope sizes a log-axis bar in log units; the edges must be transformed."""
    bar = GL_SRC.split("export const BAR_VS", 1)[1].split("export const", 1)[0]
    assert re.search(r"u_pmode\s*!=\s*0", bar), "BAR_VS has no non-affine width branch"
    assert bar.count("xyViewCoord(") >= 3, "BAR_VS must map both edges and the centre"
    # And the affine branch scales by the DATA-space slope, never map.x.
    assert re.search(r"width\s*\*\s*u_pmap\.w", bar)
    assert not re.search(r"width\s*\*\s*u_pmap\.x", bar)


def test_a_map_is_only_ever_written_beside_its_own_meta() -> None:
    """One producer (`_setAxisUniforms`), so no draw can pair them wrongly."""
    assert VIEW_SRC.count("this._map(") == 1, "_map must have exactly one caller"
    literal_writes = re.findall(r'uniform[234]f\(\s*u\(\s*"u_\w*map"', VIEW_SRC)
    assert literal_writes == [], (
        f"map uniforms must be written by _setAxisUniforms alone: {literal_writes}"
    )
