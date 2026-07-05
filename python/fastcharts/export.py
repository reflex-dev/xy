"""Standalone HTML export (§29 static-export row): JS client + spec + base64
buffers in one self-contained file — interactive with no kernel attached."""

from __future__ import annotations

import base64
import html as _html
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .figure import Figure

# Warn above this payload size; base64 carries a stated ~33% tax (§29).
EMBED_WARN_BYTES = 64 * 2**20

# Static PNG export shells out to a headless Chromium (the same engine that
# renders the chart interactively) — no Python browser dependency, no
# kaleido-class native package. Discovery order: explicit env var, then PATH,
# then the Playwright cache this repo's CI/dev images populate.
_CHROMIUM_ENV = "FASTCHARTS_CHROMIUM"
_CHROMIUM_NAMES = ("chromium", "chromium-browser", "chrome", "google-chrome")
_CHROMIUM_FALLBACKS = ("/opt/pw-browsers/chromium",)


def _json_for_inline_script(value: object) -> str:
    """JSON literal safe to embed directly inside an inline <script> block."""
    return (
        json.dumps(value, separators=(",", ":"), allow_nan=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def to_html(fig: "Figure", path: Optional[str] = None) -> str:
    """Render `fig` to a standalone interactive HTML string (optionally saved).

    User strings (title, names, labels) ride inside <script>/<title> blocks:
    HTML-sensitive JSON characters are escaped so user text cannot alter the
    script parse state, and the <title> text is entity-escaped."""
    # Lazy: bundled_js lives in widget.py, which imports anywidget — keep that
    # out of `import fastcharts` (§33 import-time budget).
    from .widget import bundled_js

    spec, blob = fig.build_payload()
    if len(blob) > EMBED_WARN_BYTES:
        import warnings

        warnings.warn(
            f"embedding {len(blob) / 2**20:.0f} MB of data (+33% as base64) "
            "into HTML; consider the aggregated embed once Tier 2 lands.",
            RuntimeWarning,
            stacklevel=3,
        )
    spec_js = _json_for_inline_script(spec)
    title_html = _html.escape(fig.title or "fastcharts")
    doc = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>{title_html}</title>
<style>
html,body{{margin:0;width:100%;min-height:100%;font-family:system-ui,sans-serif;background:#fff;}}
#chart{{width:100%;}}
</style>
</head>
<body>
<div id="chart"></div>
<script>{bundled_js("standalone")}</script>
<script>
  const spec = {spec_js};
  const b64 = "{base64.b64encode(blob).decode("ascii")}";
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  fastcharts.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);
</script>
</body>
</html>"""
    if path is not None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(doc)
    return doc


def find_chromium(explicit: Optional[str] = None) -> Optional[str]:
    """Locate a headless-capable Chromium/Chrome, or None."""
    for cand in (explicit, os.environ.get(_CHROMIUM_ENV)):
        if cand and Path(cand).exists():
            return cand
    for name in _CHROMIUM_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for cand in _CHROMIUM_FALLBACKS:
        if Path(cand).exists():
            return cand
    return None


def html_to_png(
    html: str,
    width: int,
    height: int,
    *,
    scale: float = 2.0,
    time_budget_ms: int = 4000,
    timeout_s: float = 120.0,
    chromium: Optional[str] = None,
) -> bytes:
    """Rasterize a standalone chart HTML string to PNG bytes via headless
    Chromium `--screenshot`. Pure mechanism (no Figure), so it is testable
    without numpy. `scale` is the device-pixel ratio (2 = retina-crisp)."""
    exe = find_chromium(chromium)
    if exe is None:
        raise RuntimeError(
            "static PNG export needs a Chromium/Chrome binary and none was found. "
            f"Set ${_CHROMIUM_ENV} to its path, put `chromium` on PATH, or install "
            "one (e.g. `playwright install chromium`). HTML export (to_html) needs "
            "nothing extra."
        )
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "chart.html"
        page.write_text(html, encoding="utf-8")
        shot = Path(td) / "out.png"
        proc = subprocess.run(
            [
                exe,
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--hide-scrollbars",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                f"--force-device-scale-factor={scale}",
                f"--window-size={int(width)},{int(height)}",
                f"--virtual-time-budget={int(time_budget_ms)}",
                f"--screenshot={shot}",
                page.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if not shot.exists():
            tail = (proc.stderr or "")[-500:]
            raise RuntimeError(f"Chromium produced no screenshot (exit {proc.returncode}): {tail}")
        data = shot.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError("screenshot output was not a PNG")
    return data


def to_png(
    fig: "Figure",
    path: Optional[str] = None,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    scale: float = 2.0,
    chromium: Optional[str] = None,
) -> bytes:
    """Rasterize `fig` to a PNG (bytes, optionally saved). Renders the same
    standalone HTML `to_html` produces in headless Chromium and screenshots it,
    so the pixels match the interactive chart. Fluid ("100%") sizes fall back
    to an explicit export size since a screenshot needs concrete dimensions."""
    w = width or (fig.width if isinstance(fig.width, int) else 800)
    h = height or (fig.height if isinstance(fig.height, int) else 500)
    doc = to_html(fig)
    data = html_to_png(doc, w, h, scale=scale, chromium=chromium)
    if path is not None:
        with open(path, "wb") as f:
            f.write(data)
    return data
