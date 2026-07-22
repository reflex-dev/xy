#!/usr/bin/env python3
"""Reviewed visual-identity baselines for a small deterministic gallery set.

Unlike ``visual_health_smoke.py`` (broad nonblank/occupancy coverage), this
gate compares three representative charts with a versioned semantic +
perceptual oracle. Chromium, the bundled font, viewport, DPR, downsample, and
tolerances are pinned in the manifest. Every run also executes real-browser
data, color, label, and geometry negative controls so a weakened oracle fails.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "examples" / "fastapi"))

import charts  # noqa: E402

from _app_smoke import ChromiumSession, Probe, find_chromium  # noqa: E402
from visual_health_smoke import (  # noqa: E402
    VIEW_H,
    VIEW_W,
    _assert_visual,
    _png_rgba,
)

SCHEMA_VERSION = 1
BASELINE_PATH = ROOT / "spec" / "visual-baselines" / "v1.json"
FONT_PATH = ROOT / "docs" / "app" / "xy_docs" / "assets" / "InstrumentSans-wdth-wght.ttf"
FONT_FAMILY = "XY Visual Baseline"
BASELINE_ROUTES = ("grouped-bars", "heatmap", "composed-layers")
VIEW_DPR = 1.0
DOWNSAMPLE = 10
SAMPLE_W, SAMPLE_H = VIEW_W // DOWNSAMPLE, VIEW_H // DOWNSAMPLE
MAX_MEAN_ABS_ERROR = 10.0
MAX_CHANGED_CELL_FRACTION = 0.12
CHANGED_CELL_DELTA = 30
MAX_GEOMETRY_DELTA_PX = 2.0

_CAPTURE_INIT_SCRIPT = r"""
(() => {
  let runtime;
  Object.defineProperty(window, "xy", {
    configurable: true,
    get: () => runtime,
    set: (value) => {
      if (value && typeof value.renderStandalone === "function") {
        const original = value.renderStandalone;
        value.renderStandalone = function(el, spec, buffer) {
          const view = original.call(this, el, spec, buffer);
          window.__xyVisualBaseline = {view, spec, buffer};
          return view;
        };
      }
      runtime = value;
    },
  });
})()
"""

_CORRUPT_DATA_MUTATION = r"""
const state = window.__xyVisualBaseline;
if (!state || !state.view || !state.spec || !state.buffer) {
  throw new Error("captured chart payload is unavailable");
}
const source = state.buffer instanceof ArrayBuffer
  ? new Uint8Array(state.buffer)
  : new Uint8Array(state.buffer.buffer, state.buffer.byteOffset, state.buffer.byteLength);
const bytes = new Uint8Array(source);
const spec = structuredClone(state.spec);
let changed = 0;
for (const trace of spec.traces || []) {
  const columnIndex = trace.bar && trace.bar.value1;
  const column = Number.isInteger(columnIndex) && spec.columns[columnIndex];
  if (!column || column.kind !== "float") continue;
  const values = new Float32Array(bytes.buffer, column.byte_offset, column.len);
  const encoded = (5 - (column.offset || 0)) / (column.scale || 1);
  for (let i = 0; i < values.length; i++) {
    if (values[i] !== encoded) changed++;
    values[i] = encoded;
  }
}
if (!changed) throw new Error("corrupted-data control did not alter any values");
if (!state.view.updatePayload(spec, bytes)) {
  throw new Error("corrupted-data payload update was rejected by the renderer");
}
state.view.draw();
document.querySelector("[data-xy-slot='root']").dataset.xyBaselineCorruptedValues = String(changed);
"""

NEGATIVE_CONTROLS = {
    "corrupted-data": ("grouped-bars", _CORRUPT_DATA_MUTATION),
    "wrong-color": (
        "heatmap",
        "document.querySelector('[data-xy-slot=canvas]').style.filter="
        "'hue-rotate(125deg) saturate(1.8)'",
    ),
    "wrong-label": (
        "grouped-bars",
        "document.querySelector('[data-xy-slot=title]').textContent="
        "'CORRUPTED VISUAL BASELINE LABEL'",
    ),
    "wrong-geometry": (
        "composed-layers",
        "document.querySelector('[data-xy-slot=canvas]').style.transform="
        "'translateX(52px) scaleX(.72)';"
        "document.querySelector('[data-xy-slot=canvas]').style.transformOrigin='left top'",
    ),
}

_SEMANTIC_EXPR = r"""
(() => {
  const text = (selector) => Array.from(document.querySelectorAll(selector)).map((el) => ({
    axis: el.dataset.xyAxis || "",
    side: el.dataset.xyAxisSide || "",
    text: (el.textContent || "").trim(),
  })).filter((item) => item.text);
  const slots = {};
  for (const slot of ["root", "canvas", "title", "legend", "colorbar"]) {
    slots[slot] = Array.from(document.querySelectorAll(`[data-xy-slot='${slot}']`)).map((el) => {
      const r = el.getBoundingClientRect();
      return {x: +r.x.toFixed(1), y: +r.y.toFixed(1),
              w: +r.width.toFixed(1), h: +r.height.toFixed(1)};
    });
  }
  const root = document.querySelector("[data-xy-slot='root']");
  return {
    title: text("[data-xy-slot='title']"),
    axis_titles: text("[data-xy-label-kind='axis-title']"),
    tick_labels: text("[data-xy-label-kind='tick']"),
    legend: text("[data-xy-slot='legend_item']"),
    colorbar: text("[data-xy-slot='colorbar_tick'],[data-xy-slot='colorbar_title']"),
    slots,
    font_family: root ? getComputedStyle(root).fontFamily : "",
    dpr: window.devicePixelRatio,
  };
})()
"""


class BaselineError(RuntimeError):
    pass


@contextlib.contextmanager
def _baseline_pages() -> Iterator[dict[str, str]]:
    """Build deterministic standalone gallery pages without a network hop."""
    with tempfile.TemporaryDirectory(prefix="xy-visual-baseline-pages-") as directory:
        root = Path(directory)
        urls: dict[str, str] = {}
        for route in BASELINE_ROUTES:
            path = root / f"{route}.html"
            path.write_text(charts.BY_ID[route].builder().to_html(), encoding="utf-8")
            urls[route] = path.as_uri()
        yield urls


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _font_bytes() -> bytes:
    try:
        return FONT_PATH.read_bytes()
    except OSError as exc:
        raise BaselineError(f"cannot read pinned font {FONT_PATH}: {exc}") from exc


def _playwright_version() -> str:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    version = package.get("devDependencies", {}).get("playwright")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise BaselineError("package.json must pin an exact Playwright version")
    return version


def _browser_version(executable: str) -> str:
    try:
        completed = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BaselineError(f"cannot execute configured Chromium {executable}: {exc}") from exc
    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", completed.stdout + completed.stderr)
    if completed.returncode != 0 or match is None:
        raise BaselineError(
            f"configured Chromium did not report an exact version: "
            f"exit={completed.returncode} output={(completed.stdout + completed.stderr)[-300:]!r}"
        )
    return match.group(1)


def _resolve_chromium(explicit: str | None) -> str:
    if explicit:
        candidate = explicit if Path(explicit).is_file() else shutil.which(explicit)
        if not candidate:
            raise BaselineError(f"configured chromium not found: {explicit}")
        return str(candidate)
    return find_chromium(None)


def _font_expr(font: bytes) -> str:
    encoded = base64.b64encode(font).decode("ascii")
    return f"""
(async () => {{
  const family = {json.dumps(FONT_FAMILY)};
  const bin = atob({json.dumps(encoded)});
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const face = new FontFace(family, bytes.buffer, {{weight: "100 900", style: "normal"}});
  await face.load();
  document.fonts.add(face);
  const root = document.querySelector("[data-xy-slot='root']");
  if (!root) throw new Error("visual baseline root is missing");
  root.style.fontFamily = `"${{family}}"`;
  await document.fonts.ready;
  window.dispatchEvent(new Event("resize"));
  await new Promise((resolve) => requestAnimationFrame(() =>
    requestAnimationFrame(() => requestAnimationFrame(resolve))));
  return {{loaded: document.fonts.check(`12px "${{family}}"`),
           family: getComputedStyle(root).fontFamily,
           dpr: window.devicePixelRatio}};
}})()
"""


def _capture_route(
    session: ChromiumSession,
    url: str,
    name: str,
    font: bytes,
    *,
    mutation: str | None = None,
) -> tuple[bytes, dict, dict]:
    probe = None
    stage = "create page"
    try:
        probe = Probe(
            session,
            url,
            init_script=_CAPTURE_INIT_SCRIPT,
            emulate=(VIEW_W, VIEW_H, VIEW_DPR),
        )
        stage = "wait for canvas"
        probe.wait_for(
            "!!document.querySelector('[data-xy-slot=canvas]')",
            timeout_s=60.0,
            label=f"{name}: canvas mounted",
        )
        stage = "load pinned font"
        font_info = probe.eval(_font_expr(font), timeout_s=60.0)
        if not font_info or font_info.get("loaded") is not True:
            raise BaselineError(f"{name}: pinned browser font did not load: {font_info!r}")
        if mutation:
            stage = "apply negative control"
            probe.eval(f"(() => {{{mutation}; return true;}})()")
            stage = "settle negative control"
            probe.eval("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
        stage = "capture screenshot"
        shot = probe._call(
            "Page.captureScreenshot",
            {
                "format": "png",
                "clip": {"x": 0, "y": 0, "width": VIEW_W, "height": VIEW_H, "scale": 1},
            },
        )
        png = base64.b64decode(shot["data"], validate=True)
        stage = "capture semantics"
        semantic = probe.eval(_SEMANTIC_EXPR)
        if not isinstance(semantic, dict):
            raise BaselineError(f"{name}: semantic probe returned {semantic!r}")
        return png, semantic, font_info
    except BaselineError:
        raise
    except SystemExit as exc:
        raise BaselineError(f"{name}: browser capture failed during {stage}: {exc}") from exc
    except Exception as exc:
        raise BaselineError(
            f"{name}: browser capture failed during {stage} ({type(exc).__name__}): {exc}"
        ) from exc
    finally:
        if probe is not None:
            probe.close()


def _downsample(png: bytes) -> bytes:
    width, height, rgba = _png_rgba(png)
    if (width, height) != (VIEW_W, VIEW_H):
        raise BaselineError(f"expected {VIEW_W}x{VIEW_H} PNG, got {width}x{height}")
    out = bytearray(SAMPLE_W * SAMPLE_H * 3)
    for sy in range(SAMPLE_H):
        for sx in range(SAMPLE_W):
            sums = [0, 0, 0]
            count = 0
            for y in range(sy * DOWNSAMPLE, (sy + 1) * DOWNSAMPLE):
                for x in range(sx * DOWNSAMPLE, (sx + 1) * DOWNSAMPLE):
                    offset = (y * width + x) * 4
                    r, g, b, a = rgba[offset : offset + 4]
                    alpha = a / 255.0
                    sums[0] += round(r * alpha + 255 * (1 - alpha))
                    sums[1] += round(g * alpha + 255 * (1 - alpha))
                    sums[2] += round(b * alpha + 255 * (1 - alpha))
                    count += 1
            target = (sy * SAMPLE_W + sx) * 3
            out[target : target + 3] = bytes(round(value / count) for value in sums)
    return bytes(out)


def _decode_expected(case: dict, name: str) -> bytes:
    raster = case.get("raster")
    if not isinstance(raster, str):
        raise BaselineError(f"{name}: baseline raster must be base64 text")
    try:
        raw = base64.b64decode(raster, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BaselineError(f"{name}: corrupt baseline raster: {exc}") from exc
    expected_len = SAMPLE_W * SAMPLE_H * 3
    if len(raw) != expected_len:
        raise BaselineError(
            f"{name}: baseline raster has {len(raw)} bytes, expected {expected_len}"
        )
    if case.get("raster_sha256") != _sha256(raw):
        raise BaselineError(f"{name}: baseline raster checksum mismatch")
    return raw


def _semantic_errors(expected: dict, actual: dict) -> list[str]:
    errors: list[str] = []
    for key in ("title", "axis_titles", "tick_labels", "legend", "colorbar", "font_family", "dpr"):
        if expected.get(key) != actual.get(key):
            errors.append(f"semantic {key} differs")
    expected_slots = expected.get("slots")
    actual_slots = actual.get("slots")
    if not isinstance(expected_slots, dict) or not isinstance(actual_slots, dict):
        return [*errors, "semantic slot geometry is missing"]
    if set(expected_slots) != set(actual_slots):
        errors.append("semantic slot set differs")
        return errors
    for slot, expected_rects in expected_slots.items():
        actual_rects = actual_slots.get(slot)
        if not isinstance(expected_rects, list) or not isinstance(actual_rects, list):
            errors.append(f"semantic {slot} geometry is malformed")
            continue
        if len(expected_rects) != len(actual_rects):
            errors.append(f"semantic {slot} geometry count differs")
            continue
        for index, (expected_rect, actual_rect) in enumerate(
            zip(expected_rects, actual_rects, strict=True)
        ):
            for dimension in ("x", "y", "w", "h"):
                before = expected_rect.get(dimension)
                after = actual_rect.get(dimension)
                if not isinstance(before, int | float) or not isinstance(after, int | float):
                    errors.append(f"semantic {slot}[{index}].{dimension} is malformed")
                elif abs(before - after) > MAX_GEOMETRY_DELTA_PX:
                    errors.append(
                        f"semantic {slot}[{index}].{dimension} delta "
                        f"{abs(before - after):.1f}px exceeds {MAX_GEOMETRY_DELTA_PX:.1f}px"
                    )
    return errors


def compare_case(
    name: str, png: bytes, semantic: dict, case: dict
) -> tuple[list[str], dict, bytes, bytes]:
    expected = _decode_expected(case, name)
    actual = _downsample(png)
    deltas = [abs(before - after) for before, after in zip(expected, actual, strict=True)]
    mae = sum(deltas) / len(deltas)
    changed = 0
    cells = SAMPLE_W * SAMPLE_H
    for cell in range(cells):
        start = cell * 3
        if max(deltas[start : start + 3]) > CHANGED_CELL_DELTA:
            changed += 1
    changed_fraction = changed / cells
    errors = _semantic_errors(case.get("semantic", {}), semantic)
    if mae > MAX_MEAN_ABS_ERROR:
        errors.append(f"perceptual MAE {mae:.3f} exceeds {MAX_MEAN_ABS_ERROR:.3f}")
    if changed_fraction > MAX_CHANGED_CELL_FRACTION:
        errors.append(
            f"changed-cell fraction {changed_fraction:.4f} exceeds {MAX_CHANGED_CELL_FRACTION:.4f}"
        )
    metrics = {
        "mean_abs_error": round(mae, 4),
        "changed_cell_fraction": round(changed_fraction, 6),
        "semantic_error_count": len(_semantic_errors(case.get("semantic", {}), semantic)),
    }
    return errors, metrics, expected, actual


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _rgb_png(width: int, height: int, rgb: bytes) -> bytes:
    if len(rgb) != width * height * 3:
        raise BaselineError("RGB artifact byte length does not match geometry")
    raw = b"".join(b"\x00" + rgb[y * width * 3 : (y + 1) * width * 3] for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


def _diff_rgb(expected: bytes, actual: bytes) -> bytes:
    out = bytearray(len(expected))
    for offset in range(0, len(expected), 3):
        delta = max(abs(expected[offset + i] - actual[offset + i]) for i in range(3))
        if delta <= 2:
            out[offset : offset + 3] = b"\xff\xff\xff"
        else:
            out[offset : offset + 3] = bytes(
                (min(255, 40 + delta * 5), max(0, 220 - delta * 3), 32)
            )
    return bytes(out)


def write_artifacts(
    root: Path,
    name: str,
    *,
    full_png: bytes,
    expected: bytes,
    actual: bytes,
    expected_semantic: dict,
    actual_semantic: dict,
) -> None:
    destination = root / name
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "expected.png").write_bytes(_rgb_png(SAMPLE_W, SAMPLE_H, expected))
    (destination / "actual.png").write_bytes(_rgb_png(SAMPLE_W, SAMPLE_H, actual))
    (destination / "actual-full.png").write_bytes(full_png)
    (destination / "diff.png").write_bytes(
        _rgb_png(SAMPLE_W, SAMPLE_H, _diff_rgb(expected, actual))
    )
    (destination / "expected-semantic.json").write_text(
        json.dumps(expected_semantic, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (destination / "actual-semantic.json").write_text(
        json.dumps(actual_semantic, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _load_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineError(f"cannot read visual baseline manifest {path}: {exc}") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise BaselineError(
            f"unsupported visual baseline schema {manifest.get('schema_version')!r}"
        )
    if manifest.get("suite") != "xy-reviewed-visual-baselines":
        raise BaselineError("visual baseline suite identity is missing or invalid")
    if set(manifest.get("cases", {})) != set(BASELINE_ROUTES):
        raise BaselineError("visual baseline route set does not match the required bounded set")
    pinned = manifest.get("pinned", {})
    if pinned.get("browser_engine") != "chromium":
        raise BaselineError("visual baselines require the Chromium browser engine")
    if not isinstance(pinned.get("browser_version"), str) or not re.fullmatch(
        r"\d+\.\d+\.\d+\.\d+", pinned["browser_version"]
    ):
        raise BaselineError("visual baseline browser_version must be an exact four-part version")
    expected_pin = {
        "playwright": _playwright_version(),
        "viewport": [VIEW_W, VIEW_H],
        "dpr": VIEW_DPR,
        "font_path": str(FONT_PATH.relative_to(ROOT)),
        "font_sha256": _sha256(_font_bytes()),
        "downsample": DOWNSAMPLE,
    }
    for key, value in expected_pin.items():
        if pinned.get(key) != value:
            raise BaselineError(
                f"visual baseline pin {key!r} is stale: {pinned.get(key)!r} != {value!r}"
            )
    expected_tolerances = {
        "max_mean_abs_error": MAX_MEAN_ABS_ERROR,
        "max_changed_cell_fraction": MAX_CHANGED_CELL_FRACTION,
        "changed_cell_delta": CHANGED_CELL_DELTA,
        "max_geometry_delta_px": MAX_GEOMETRY_DELTA_PX,
    }
    if manifest.get("tolerances") != expected_tolerances:
        raise BaselineError("visual baseline tolerances differ from the reviewed code constants")
    update = manifest.get("update", {})
    if (
        not isinstance(update.get("prepared_by"), str)
        or not update["prepared_by"].strip()
        or not isinstance(update.get("reason"), str)
        or not update["reason"].strip()
        or update.get("review_required") is not True
    ):
        raise BaselineError("visual baseline update provenance is missing or invalid")
    for name, case in manifest["cases"].items():
        _decode_expected(case, name)
    return manifest


def _load_review_source(path: Path) -> dict | None:
    """Load the previous reviewed pixels for proposal artifacts.

    Existing environment pins are deliberately not checked here: updating a
    browser, font, or Playwright pin is one reason a proposal may be needed.
    The old raster checksums and bounded route set must still be intact.
    """
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineError(f"cannot read prior visual baseline {path}: {exc}") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise BaselineError("prior visual baseline schema cannot be used for review artifacts")
    if set(manifest.get("cases", {})) != set(BASELINE_ROUTES):
        raise BaselineError("prior visual baseline route set is incomplete")
    for name, case in manifest["cases"].items():
        _decode_expected(case, name)
    return manifest


def _new_manifest(
    *,
    browser_version: str,
    font: bytes,
    prepared_by: str,
    reason: str,
    captures: dict[str, tuple[bytes, dict]],
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "suite": "xy-reviewed-visual-baselines",
        "pinned": {
            "browser_engine": "chromium",
            "browser_version": browser_version,
            "playwright": _playwright_version(),
            "viewport": [VIEW_W, VIEW_H],
            "dpr": VIEW_DPR,
            "font_path": str(FONT_PATH.relative_to(ROOT)),
            "font_sha256": _sha256(font),
            "downsample": DOWNSAMPLE,
        },
        "tolerances": {
            "max_mean_abs_error": MAX_MEAN_ABS_ERROR,
            "max_changed_cell_fraction": MAX_CHANGED_CELL_FRACTION,
            "changed_cell_delta": CHANGED_CELL_DELTA,
            "max_geometry_delta_px": MAX_GEOMETRY_DELTA_PX,
        },
        "update": {
            "prepared_by": prepared_by,
            "reason": reason,
            "prepared_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "review_required": True,
        },
        "cases": {
            name: {
                "semantic": semantic,
                "raster": base64.b64encode(sample).decode("ascii"),
                "raster_sha256": _sha256(sample),
            }
            for name, (sample, semantic) in captures.items()
        },
    }


def _write_evidence(path: Path | None, payload: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run(args: argparse.Namespace, artifacts: Path) -> tuple[int, dict]:
    executable = _resolve_chromium(args.chromium)
    browser_version = _browser_version(executable)
    font = _font_bytes()
    prepared_by = args.prepared_by.strip() if isinstance(args.prepared_by, str) else ""
    reason = args.reason.strip() if isinstance(args.reason, str) else ""
    review_source = None
    if args.update_baselines:
        if os.environ.get("CI"):
            raise BaselineError("baseline updates are forbidden in CI")
        if not prepared_by or not reason:
            raise BaselineError("--update-baselines requires --prepared-by and --reason")
        review_source = _load_review_source(args.baseline)
    manifest = None if args.update_baselines else _load_manifest(args.baseline)
    if manifest is not None and manifest["pinned"].get("browser_version") != browser_version:
        raise BaselineError(
            f"visual baselines require Chromium {manifest['pinned'].get('browser_version')}, "
            f"got {browser_version}; use the pinned Playwright executable"
        )

    captures: dict[str, tuple[bytes, dict]] = {}
    full_captures: dict[str, bytes] = {}
    results: dict[str, dict] = {}
    failures: list[str] = []
    with (
        _baseline_pages() as urls,
        ChromiumSession(executable, gl="software", sandbox=False) as session,
    ):
        for route in BASELINE_ROUTES:
            png, semantic, font_info = _capture_route(session, urls[route], route, font)
            health_error = None
            try:
                _assert_visual(route, png)
            except SystemExit as exc:
                health_error = f"visual health failure: {exc}"
            sample = _downsample(png)
            captures[route] = (sample, semantic)
            full_captures[route] = png
            if manifest is not None:
                errors, metrics, expected, actual = compare_case(
                    route, png, semantic, manifest["cases"][route]
                )
                if health_error:
                    errors.insert(0, health_error)
                results[route] = {"errors": errors, "metrics": metrics, "font": font_info}
                if errors:
                    failures.extend(f"{route}: {error}" for error in errors)
                    write_artifacts(
                        artifacts,
                        route,
                        full_png=png,
                        expected=expected,
                        actual=actual,
                        expected_semantic=manifest["cases"][route]["semantic"],
                        actual_semantic=semantic,
                    )
            elif health_error:
                failures.append(f"{route}: {health_error}")
                results[route] = {"errors": [health_error], "font": font_info}

        if args.update_baselines:
            manifest = _new_manifest(
                browser_version=browser_version,
                font=font,
                prepared_by=prepared_by,
                reason=reason,
                captures=captures,
            )
            for route, (actual, actual_semantic) in captures.items():
                if review_source is None:
                    expected = actual
                    expected_semantic = actual_semantic
                else:
                    expected_case = review_source["cases"][route]
                    expected = _decode_expected(expected_case, route)
                    expected_semantic = expected_case["semantic"]
                write_artifacts(
                    artifacts,
                    route,
                    full_png=full_captures[route],
                    expected=expected,
                    actual=actual,
                    expected_semantic=expected_semantic,
                    actual_semantic=actual_semantic,
                )

        negative_results: dict[str, dict] = {}
        for control, (route, mutation) in NEGATIVE_CONTROLS.items():
            png, semantic, _ = _capture_route(
                session,
                urls[route],
                f"negative-{control}",
                font,
                mutation=mutation,
            )
            errors, metrics, expected, actual = compare_case(
                f"negative-{control}", png, semantic, manifest["cases"][route]
            )
            rejected = bool(errors)
            negative_results[control] = {
                "route": route,
                "rejected": rejected,
                "errors": errors,
                "metrics": metrics,
            }
            write_artifacts(
                artifacts,
                f"negative-{control}",
                full_png=png,
                expected=expected,
                actual=actual,
                expected_semantic=manifest["cases"][route]["semantic"],
                actual_semantic=semantic,
            )
            if not rejected:
                failures.append(f"negative control {control!r} escaped the visual oracle")

    if args.update_baselines and not failures:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"visual baseline proposal written: {args.baseline}")
        print("attach the generated expected/actual/diff artifacts and request independent review")

    evidence = {
        "status": "failed" if failures else "ok",
        "browser_version": browser_version,
        "playwright_version": _playwright_version(),
        "font_sha256": _sha256(font),
        "viewport": [VIEW_W, VIEW_H],
        "dpr": VIEW_DPR,
        "baseline": str(args.baseline),
        "updated": bool(args.update_baselines),
        "cases": results,
        "negative_controls": negative_results,
        "failures": failures,
    }
    if failures:
        print("reviewed visual baseline FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1, evidence
    print(
        f"reviewed visual baseline OK: {len(BASELINE_ROUTES)} cases, "
        f"{len(NEGATIVE_CONTROLS)} real-browser negative controls"
    )
    return 0, evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chromium", nargs="?", default=None)
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    parser.add_argument("--artifacts", type=Path, default=None)
    parser.add_argument("--evidence", type=Path, default=None)
    parser.add_argument("--update-baselines", action="store_true")
    parser.add_argument("--prepared-by", default=None)
    parser.add_argument("--reason", default=None)
    args = parser.parse_args(argv)

    temporary = tempfile.TemporaryDirectory() if args.artifacts is None else None
    artifacts = args.artifacts or Path(temporary.name)
    evidence = {
        "status": "failed",
        "error": "visual baseline exited before producing evidence",
        "baseline": str(args.baseline),
        "updated": bool(args.update_baselines),
    }
    try:
        rc, evidence = _run(args, artifacts)
    except (Exception, SystemExit) as exc:
        evidence = {
            "status": "failed",
            "error": str(exc),
            "baseline": str(args.baseline),
            "updated": bool(args.update_baselines),
        }
        print(f"reviewed visual baseline FAILED: {exc}", file=sys.stderr)
        rc = 1
    finally:
        _write_evidence(args.evidence, evidence)
        if temporary is not None:
            temporary.cleanup()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
