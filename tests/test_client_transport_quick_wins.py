"""Real-browser coverage for the #176 client transport investigation."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_browser_probe
from xy._figure import Figure
from xy.export import find_chromium

_RENDER_CALL = 'xy.renderStandalone(document.getElementById("chart"), spec, buf);'


def _run_probe(tmp_path: Path, figure: Figure, script: str, attribute: str) -> dict:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    html = figure.to_html()
    document = html.replace(_RENDER_CALL, script)
    assert document != html
    return run_browser_probe(
        chromium,
        document,
        tmp_path / f"{attribute}.html",
        attribute,
        label=attribute,
    )


_STYLE_PROBE = r"""
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    if (view._raf) cancelAnimationFrame(view._raf);
    view._raf = null;
    view.gl.finish();
    const traces = view.gpuTraces.map((g) => {
      let packed = [];
      if (g.styleBuf) {
        const values = new Float32Array(g.n * g.styleSize);
        view.gl.bindBuffer(view.gl.ARRAY_BUFFER, g.styleBuf);
        view.gl.getBufferSubData(view.gl.ARRAY_BUFFER, 0, values);
        packed = Array.from(values);
      }
      return {
        bytes: g.styleBuf ? g.styleBuf._fcBytes : 0,
        size: g.styleSize,
        base: g.styleBase,
        slots: g.styleSlots,
        packed,
      };
    });
    const pixelAt = (g, index) => {
      const x = view._decodeValue(g._cpu.x, g.xMeta, index);
      const y = view._decodeValue(g._cpu.y, g.yMeta, index);
      const cssX = view._dataPx(g.xAxis, x) - view.plot.x;
      const cssY = view._dataPx(g.yAxis, y) - view.plot.y;
      const out = new Uint8Array(4);
      view.gl.bindFramebuffer(view.gl.FRAMEBUFFER, null);
      view.gl.readPixels(
        Math.round(cssX * view.dpr),
        Math.round((view.plot.h - cssY) * view.dpr),
        1, 1, view.gl.RGBA, view.gl.UNSIGNED_BYTE, out,
      );
      return Array.from(out);
    };
    const alphaPixels = [pixelAt(view.gpuTraces[0], 0), pixelAt(view.gpuTraces[0], 1)];
    const constantArtistPixel = pixelAt(view.gpuTraces[1], 0);
    document.body.setAttribute("data-xy-style-pack", JSON.stringify({
      traces,
      alphaPixels,
      constantArtistPixel,
      glError: view.gl.getError(),
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-style-pack-error", String((err && err.stack) || err));
  }
"""


def test_style_channels_pack_without_padding_and_render_with_exact_slots(tmp_path: Path) -> None:
    fig = Figure(width=520, height=340)
    fig.scatter(
        [-0.9, -0.5],
        [0.0, 0.0],
        opacity=[0.25, 0.75],
        color="#2563eb",
        size=36,
        symbol="square",
        density=False,
    )
    fig.scatter(
        [0.0],
        [0.0],
        opacity=0.8,
        _artist_alpha=0.35,
        color="#16a34a",
        size=36,
        symbol="square",
        density=False,
    )
    fig.scatter(
        [0.5, 0.9],
        [0.0, 0.0],
        opacity=[0.4, 0.9],
        _artist_alpha=[0.2, 0.7],
        color="#dc2626",
        size=36,
        symbol=["diamond", "triangle"],
        stroke="#111827",
        stroke_width=[1.0, 3.0],
        density=False,
    )

    result = _run_probe(tmp_path, fig, _STYLE_PROBE, "data-xy-style-pack")
    one, constant, four = result["traces"]
    assert result["glError"] == 0

    assert one["size"] == 1
    assert one["bytes"] == 2 * 4
    assert one["slots"] == [0, -1, -1, -1]
    assert one["packed"] == pytest.approx([0.25, 0.75])

    assert constant["size"] == 0
    assert constant["bytes"] == 0
    assert constant["slots"] == [-1, -1, -1, -1]
    assert constant["base"] == pytest.approx([1.0, 0.35, -1.0, -1.0])

    assert four["size"] == 4
    assert four["bytes"] == 2 * 4 * 4
    assert four["slots"] == [0, 1, 2, 3]
    assert four["packed"][:4] == pytest.approx([0.4, 0.2, 1.0, 2.0])
    assert four["packed"][4:] == pytest.approx([0.9, 0.7, 3.0, 3.0])

    # The packed scalar is consumed by the real shader: 0.75 opacity must
    # produce roughly 3x the alpha of 0.25 at marker centers.
    low_alpha = result["alphaPixels"][0][3]
    high_alpha = result["alphaPixels"][1][3]
    assert low_alpha > 0
    assert high_alpha / low_alpha == pytest.approx(3.0, rel=0.08)
    # A scalar artist alpha stays out of a buffer but still reaches the shader.
    assert result["constantArtistPixel"][3] == pytest.approx(0.35 * 0.8 * 255, abs=4)


_STYLE_FAMILIES_PROBE = r"""
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    if (view._raf) cancelAnimationFrame(view._raf);
    view._raf = null;
    view.gl.finish();
    const describe = (g) => {
      let bufferSize = 0;
      if (g.styleBuf) {
        view.gl.bindBuffer(view.gl.ARRAY_BUFFER, g.styleBuf);
        bufferSize = view.gl.getBufferParameter(view.gl.ARRAY_BUFFER, view.gl.BUFFER_SIZE);
      }
      return {
        kind: g.trace.kind,
        n: g.n,
        size: g.styleSize,
        slots: g.styleSlots,
        bufferSize,
        sample: g.sampleOverlay ? describe(g.sampleOverlay) : null,
      };
    };

    // Reuse one object exactly as drill refreshes do. Exercise every single
    // semantic slot plus 2/3/4-channel layouts and the uniform-only teardown.
    const reused = {};
    const n = 7;
    const sources = {
      opacity: new Float32Array(n).fill(0.25),
      artist_alpha: new Float32Array(n).fill(0.5),
      stroke_width: new Float32Array(n).fill(2),
      symbol: new Uint8Array(n).fill(3),
    };
    const packedCases = [];
    const run = (names, artistScalar = NaN) => {
      const specs = Object.fromEntries(names.map((name) => [name, {
        components: 1,
        dtype: name === "symbol" ? "u8" : "f32",
        source: sources[name],
      }]));
      view._packInstanceStyleChannels(
        reused, n, (name) => specs[name], artistScalar,
        (item) => item.source, "stroke_width",
      );
      packedCases.push(describe({ ...reused, trace: {kind: "reused"}, n }));
    };
    run(["opacity"]);
    run(["artist_alpha"]);
    run(["stroke_width"]);
    run(["symbol"]);
    run(["opacity", "artist_alpha"]);
    run(["opacity", "artist_alpha", "stroke_width"]);
    run(["opacity", "artist_alpha", "stroke_width", "symbol"]);
    run([], 0.4);

    document.body.setAttribute("data-xy-style-families", JSON.stringify({
      traces: view.gpuTraces.map(describe),
      packedCases,
      glError: view.gl.getError(),
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-style-families-error", String((err && err.stack) || err),
    );
  }
"""


def test_style_packing_spans_all_slots_mark_shaders_and_reused_samples(tmp_path: Path) -> None:
    fig = Figure(width=620, height=420)
    # Point: symbol-only scalar layout (w slot).
    fig.scatter([-3.0, -2.5], [3.0, 3.2], symbol=["square", "diamond"], density=False)
    # Segment: width-only scalar layout (z slot).
    fig.segments([-3.0, -2.5], [2.0, 2.2], [-2.7, -2.2], [2.3, 2.5], width=[1, 2])
    # Mesh: two packed channels (opacity + stroke width).
    fig.triangle_mesh(
        [-1.8, -1.1],
        [1.0, 1.0],
        [-1.4, -0.7],
        [1.7, 1.7],
        [-1.0, -0.3],
        [1.0, 1.0],
        opacity=[0.4, 0.8],
        stroke="#111827",
        stroke_width=[1, 2],
    )
    # Compact bar and rect shaders: three packed channels.
    fig.bar(
        [0.5, 1.5],
        [1.0, 1.8],
        opacity=[0.45, 0.9],
        _artist_alpha=[0.3, 0.7],
        stroke="#111827",
        stroke_width=[1, 2],
    )
    fig.histogram(
        [2.1, 2.2, 2.6, 2.7],
        bins=2,
        opacity=[0.5, 0.85],
        _artist_alpha=[0.25, 0.75],
        stroke="#111827",
        stroke_width=[1, 3],
    )
    # Actual retained density sample uses the same helper as drill updates.
    density_x = [3.0 + i / 1000 for i in range(1000)]
    fig.scatter(
        density_x,
        density_x,
        opacity=[0.2 + i / 2000 for i in range(1000)],
        density=True,
    )

    result = _run_probe(tmp_path, fig, _STYLE_FAMILIES_PROBE, "data-xy-style-families")
    assert result["glError"] == 0
    traces = result["traces"]
    by_kind = {trace["kind"]: trace for trace in traces}
    direct_scatter = next(
        trace for trace in traces if trace["kind"] == "scatter" and trace["sample"] is None
    )
    assert direct_scatter["size"] == 1
    assert direct_scatter["slots"] == [-1, -1, -1, 0]
    assert direct_scatter["bufferSize"] == direct_scatter["n"] * 4
    assert by_kind["segments"]["slots"] == [-1, -1, 0, -1]
    assert by_kind["segments"]["bufferSize"] == by_kind["segments"]["n"] * 4
    assert by_kind["triangle_mesh"]["size"] == 2
    assert by_kind["triangle_mesh"]["slots"] == [0, -1, 1, -1]
    assert by_kind["triangle_mesh"]["bufferSize"] == by_kind["triangle_mesh"]["n"] * 8
    assert by_kind["bar"]["size"] == 3
    assert by_kind["bar"]["slots"] == [0, 1, 2, -1]
    assert by_kind["bar"]["bufferSize"] == by_kind["bar"]["n"] * 12
    assert by_kind["histogram"]["size"] == 3
    assert by_kind["histogram"]["bufferSize"] == by_kind["histogram"]["n"] * 12
    density = next(trace for trace in traces if trace["sample"] is not None)
    assert density["sample"]["size"] == 1
    assert density["sample"]["slots"] == [0, -1, -1, -1]
    assert density["sample"]["bufferSize"] == density["sample"]["n"] * 4

    cases = result["packedCases"]
    assert [case["slots"] for case in cases[:4]] == [
        [0, -1, -1, -1],
        [-1, 0, -1, -1],
        [-1, -1, 0, -1],
        [-1, -1, -1, 0],
    ]
    assert [case["bufferSize"] for case in cases] == [
        7 * 4,
        7 * 4,
        7 * 4,
        7 * 4,
        7 * 8,
        7 * 12,
        7 * 16,
        0,
    ]


_APPEND_PROBE = r"""
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    const pairsFor = (oldValues, newValues, oldMeta = {offset: 0, scale: 1},
                      newMeta = {offset: 0, scale: 1}) => view._transitionMatches(
      { n: oldValues.length, _cpu: { x: oldValues }, xMeta: oldMeta },
      { n: newValues.length, _cpu: { x: newValues }, xMeta: newMeta,
        trace: { animation_fallback: null } },
      { match: "append" },
    ).pairs;

    // These are deliberately on decimal-rounding boundaries where an
    // allocation-free numeric key can change identity semantics.
    const boundaryPairs = pairsFor(
      new Float64Array([8.952695812915, 1234567890125, -0]),
      new Float64Array([8.95269581290906, 1234567890124.9973, +0]),
    );

    const canonical = Array.from({length: 512}, (_, i) => 1700000000000 + i * 1000.25);
    const encode = (values, offset) => new Float32Array(values.map((v) => v - offset));
    const oldOffset = 1700000250000;
    const nextOffset = 1700000320000;
    const offsetPairs = pairsFor(
      encode(canonical, oldOffset),
      encode([...canonical, 1700000800000], nextOffset),
      { offset: oldOffset, scale: 1 },
      { offset: nextOffset, scale: 1 },
    );

    // Exercise the issue's exact proposal, both as Math.fround numeric Map
    // keys and as the equivalent f32 bit pattern from reusable typed views.
    // Counting only Map.has() would hide the bug: collisions still "match"
    // but return the wrong old row, so exact source indices are the oracle.
    const f32Storage = new ArrayBuffer(4);
    const f32Value = new Float32Array(f32Storage);
    const f32Bits = new Uint32Array(f32Storage);
    const f32BitsKey = (value) => {
      if (value === 0) return 0;
      f32Value[0] = value;
      return f32Bits[0];
    };
    const oldEncoded = encode(canonical, oldOffset);
    const newEncoded = encode(canonical, nextOffset);
    const decoded = (values, offset, i) => values[i] + offset;
    const candidateOracle = {};
    const keyFns = {
      string: (value) => value.toPrecision(12),
      fround: (value) => Math.fround(value),
      f32_bits: f32BitsKey,
    };
    for (const [name, key] of Object.entries(keyFns)) {
      const index = new Map();
      for (let i = 0; i < canonical.length; i++) {
        index.set(key(decoded(oldEncoded, oldOffset, i)), i);
      }
      let exactMatches = 0;
      for (let i = 0; i < canonical.length; i++) {
        if (index.get(key(decoded(newEncoded, nextOffset, i))) === i) exactMatches++;
      }
      candidateOracle[name] = {
        uniqueOldKeys: index.size,
        exactMatches,
        boundaryMatch: key(8.952695812915) === key(8.95269581290906),
        boundaryMiss: key(1234567890125) !== key(1234567890124.9973),
        epochAdjacentDistinct: key(1700000000000) !== key(1700000001024),
      };
    }
    document.body.setAttribute("data-xy-append-identity", JSON.stringify({
      boundaryPairs,
      offsetPairCount: offsetPairs.length,
      offsetFirst: offsetPairs[0],
      offsetLast: offsetPairs[offsetPairs.length - 1],
      candidateOracle,
    }));
  } catch (err) {
    document.body.setAttribute(
      "data-xy-append-identity-error", String((err && err.stack) || err),
    );
  }
"""


def test_append_matching_keeps_decimal_identity_boundaries_and_offset_columns(
    tmp_path: Path,
) -> None:
    fig = Figure(width=360, height=240).scatter([0.0, 1.0], [0.0, 1.0])
    result = _run_probe(tmp_path, fig, _APPEND_PROBE, "data-xy-append-identity")
    # First pair must match; second must not; signed zero remains one identity.
    assert result["boundaryPairs"] == [[0, 0], [2, 2]]
    assert result["offsetPairCount"] == 512
    assert result["offsetFirst"] == [0, 0]
    assert result["offsetLast"] == [511, 511]
    oracle = result["candidateOracle"]
    assert oracle["string"] == {
        "uniqueOldKeys": 512,
        "exactMatches": 512,
        "boundaryMatch": True,
        "boundaryMiss": True,
        "epochAdjacentDistinct": True,
    }
    assert oracle["fround"] == oracle["f32_bits"]
    assert oracle["fround"]["uniqueOldKeys"] < 512
    assert oracle["fround"]["exactMatches"] < 512
    assert oracle["fround"]["boundaryMatch"] is True
    assert oracle["fround"]["boundaryMiss"] is False
    assert oracle["fround"]["epochAdjacentDistinct"] is False


_PICK_PROBE = r"""
  const view = xy.renderStandalone(document.getElementById("chart"), spec, buf);
  try {
    view._drawNow();
    if (view._raf) cancelAnimationFrame(view._raf);
    view._raf = null;
    const g = view.gpuTraces[0];
    const realRenderPick = view._renderPick;
    let pickRenders = 0;
    view._renderPick = function () {
      pickRenders += 1;
      return realRenderPick.call(this);
    };
    const x = view.plot.w * 0.5, y = view.plot.h * 0.5;
    view._pickDirty = true;
    view._pickAt(x, y);
    const bufferAfterFirst = view._pickPixel;
    const rendersBeforeBlend = pickRenders;

    // Native-color density handoff changes only fragment paint. Its scheduled
    // frame must keep the existing pick geometry valid.
    view._prefersReducedMotion = () => false;
    g.lodBlendShown = 1;
    g.lodBlend = 0;
    g._blendTick = view._now() - 16;
    // This is a normal current frame (e.g. fresh drill geometry) that happens
    // to schedule a color-only blend continuation from inside _drawPoints.
    view._rafKeepPick = false;
    view._drawNow();
    const currentGeometryFrameInvalidated = view._pickDirty;
    const continuationScheduledKeepPick = view._rafKeepPick === true;
    if (view._raf) cancelAnimationFrame(view._raf);
    view._raf = null;
    // Refresh the now-invalid snapshot, then execute the queued color-only
    // continuation with its captured keep-pick flag.
    view._pickAt(x + 1, y);
    view._drawNow();
    const continuationPreservedPick = !view._pickDirty;
    if (view._raf) cancelAnimationFrame(view._raf);
    view._raf = null;
    view._pickAt(x + 1, y);
    const reusedReadBuffer = bufferAfterFirst === view._pickPixel;

    // True geometry/tier fades still suppress hover reads altogether.
    const realPickAt = view._pickAt;
    let readsDuringTierFade = 0;
    view._pickAt = () => { readsDuringTierFade += 1; return null; };
    g._drillFadeStart = view._now();
    const rect = view.canvas.getBoundingClientRect();
    view._hover({ clientX: rect.left + x, clientY: rect.top + y });
    g._drillFadeStart = null;
    view._pickAt = realPickAt;

    document.body.setAttribute("data-xy-pick-quick-win", JSON.stringify({
      rendersBeforeBlend,
      rendersAfterBlend: pickRenders,
      currentGeometryFrameInvalidated,
      continuationScheduledKeepPick,
      continuationPreservedPick,
      reusedReadBuffer,
      readsDuringTierFade,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-pick-quick-win-error", String((err && err.stack) || err));
  }
"""


def test_density_color_blend_keeps_pick_snapshot_and_read_buffer(tmp_path: Path) -> None:
    n = 50_000
    x = [float(i) for i in range(n)]
    fig = Figure(width=500, height=320).scatter(x, x, density=False, opacity=0.8)
    result = _run_probe(tmp_path, fig, _PICK_PROBE, "data-xy-pick-quick-win")
    assert result["rendersBeforeBlend"] == 1
    assert result["rendersAfterBlend"] == 2
    assert result["currentGeometryFrameInvalidated"] is True
    assert result["continuationScheduledKeepPick"] is True
    assert result["continuationPreservedPick"] is True
    assert result["reusedReadBuffer"] is True
    assert result["readsDuringTierFade"] == 0
