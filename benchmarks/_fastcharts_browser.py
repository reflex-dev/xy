"""Shared browser probes for fastcharts benchmark pages.

The regular TTFR helper in ``_browser.py`` answers "when did a page first
paint?". These helpers are for richer fastcharts-specific pages that need the
``ChartView`` object, WebGL readback, and structured JSON results from
headless Chromium.
"""

from __future__ import annotations

import base64
import html as html_lib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from _browser import chromium_gl_flags, find_chromium


def json_bytes(obj: Any) -> int:
    return len(json.dumps(obj, separators=(",", ":"), default=str).encode("utf-8"))


def inline_json(obj: Any) -> str:
    """JSON safe enough for generated benchmark data inside a script tag."""
    return json.dumps(obj, separators=(",", ":"), default=str).replace("</", "<\\/")


def _standalone_js() -> str:
    import fastcharts

    path = Path(fastcharts.__file__).resolve().parent / "static" / "standalone.js"
    return path.read_text(encoding="utf-8")


def chart_payload(id: str, spec: dict[str, Any], blob: bytes) -> dict[str, Any]:
    return {
        "id": id,
        "spec": spec,
        "b64": base64.b64encode(blob).decode("ascii"),
    }


def page_for_charts(
    charts: list[dict[str, Any]],
    probe_js: str,
    *,
    title: str,
    body_css: str = "",
) -> str:
    payloads = inline_json(charts)
    css = body_css or (
        "html,body{margin:0;background:#fff;font-family:system-ui,sans-serif;}#root{padding:0;}"
    )
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{html_lib.escape(title)}</title>
<style>{css}</style>
</head>
<body>
<div id="root"></div>
<script>{_standalone_js()}</script>
<script>
const FC_CHARTS = {payloads};
function fcBytesFromB64(b64) {{
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}}
function fcReport(marker, payload) {{
  document.title = marker + " " + JSON.stringify(payload);
}}
function fcFail(marker, err) {{
  const msg = (err && (err.stack || err.message)) ? (err.stack || err.message) : String(err);
  document.title = "FC_ERROR " + marker + " " + msg.slice(0, 480);
}}
function fcRaf() {{
  return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
}}
function fcPercentile(values, p) {{
  if (!values.length) return null;
  const sorted = values.slice().sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return sorted[idx];
}}
function fcStats(values) {{
  return {{
    min_ms: fcPercentile(values, 0),
    median_ms: fcPercentile(values, 50),
    p95_ms: fcPercentile(values, 95),
    p99_ms: fcPercentile(values, 99),
    max_ms: fcPercentile(values, 100),
    reps: values.length,
  }};
}}
function fcNonblankPixels(view) {{
  const gl = view.gl;
  view._drawNow();
  const w = Math.max(1, Math.min(64, view.canvas.width));
  const h = Math.max(1, Math.min(64, view.canvas.height));
  const x = Math.max(0, Math.floor((view.canvas.width - w) / 2));
  const y = Math.max(0, Math.floor((view.canvas.height - h) / 2));
  const pixels = new Uint8Array(w * h * 4);
  gl.readPixels(x, y, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  let count = 0;
  for (let i = 0; i < pixels.length; i += 4) {{
    if (pixels[i] || pixels[i + 1] || pixels[i + 2] || pixels[i + 3]) count++;
  }}
  return count;
}}
{probe_js}
</script>
</body>
</html>"""


def run_json_probe(
    html: str,
    *,
    marker: str,
    chromium: str | None,
    virtual_time_ms: int | None = 15_000,
    timeout_s: int = 180,
) -> dict[str, Any]:
    exe = find_chromium(chromium)
    if not exe:
        return {"status": "skipped(no chromium)"}

    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "probe.html"
        page.write_text(html, encoding="utf-8")
        try:
            command = [
                exe,
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                *chromium_gl_flags(),
                "--hide-scrollbars",
                "--enable-precise-memory-info",
            ]
            if virtual_time_ms is not None:
                command.append(f"--virtual-time-budget={virtual_time_ms}")
            command.extend(["--dump-dom", page.as_uri()])
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return {"status": "failed(timeout)"}

    match = re.search(r"<title>(.*?)</title>", completed.stdout, flags=re.IGNORECASE | re.S)
    title_text = html_lib.unescape(match.group(1).strip()) if match else ""
    prefix = f"{marker} "
    if title_text.startswith(prefix):
        try:
            payload = json.loads(title_text[len(prefix) :])
        except json.JSONDecodeError as exc:
            return {"status": f"failed(bad probe JSON: {exc})"}
        payload.setdefault("status", "ok")
        return payload
    if title_text.startswith("FC_ERROR "):
        return {"status": f"failed({title_text[:220]})"}
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout).strip().splitlines()
        return {"status": f"failed(chromium exit {completed.returncode}: {err[:1]})"}
    return {"status": "failed(no probe title)"}
