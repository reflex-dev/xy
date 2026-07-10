"""Standalone HTML export (§29 static-export row): JS client + spec + base64
buffers in one self-contained file — interactive with no kernel attached."""

from __future__ import annotations

import base64
import html as _html
import json
import math
import numbers
import os
import re as _re
import shutil
import subprocess
import tempfile
from contextlib import suppress
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Optional, SupportsFloat, SupportsIndex, cast

if TYPE_CHECKING:
    from ._figure import Figure

# Warn above this payload size; base64 carries a stated ~33% tax (§29).
EMBED_WARN_BYTES = 64 * 2**20

# Static PNG export shells out to a headless Chromium (the same engine that
# renders the chart interactively) — no Python browser dependency, no
# kaleido-class native package. Discovery order: explicit env var, then PATH,
# then common local/CI browser installs.
_CHROMIUM_ENV = "XY_CHROMIUM"
_CHROMIUM_NAMES = ("chromium", "chromium-browser", "chrome", "google-chrome")
_CHROMIUM_FALLBACKS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "/opt/pw-browsers/chromium",
)
_STATIC = Path(__file__).parent / "static"
_STANDALONE_CSP = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "img-src data:; "
    "connect-src 'none'; "
    # blob: only — the density re-bin worker boots from a Blob URL of its own
    # bundled source; no external worker script can ever load.
    "worker-src blob:; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)


def _bundled_js(which: str = "standalone") -> str:
    """Read a bundled client build without importing the notebook widget stack."""
    name = "index.js" if which == "widget" else "standalone.js"
    path = _STATIC / name
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing — the JS client was not bundled into this install. "
            "Dev checkout: run `npm run build` in js/."
        )
    return path.read_text(encoding="utf-8")


def _positive_pixel_count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise ValueError(f"{label} must be a positive integer pixel count")
    out = int(value)
    if out <= 0:
        raise ValueError(f"{label} must be a positive integer pixel count")
    return out


def _positive_finite_float(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite positive number")
    convertible = cast(str | bytes | bytearray | SupportsFloat | SupportsIndex, value)
    try:
        out = float(convertible)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite positive number") from exc
    if not math.isfinite(out) or out <= 0:
        raise ValueError(f"{label} must be a finite positive number")
    return out


def _bool_option(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{label} must be True or False")


def _json_for_inline_script(value: object) -> str:
    """JSON literal safe to embed directly inside an inline <script> block."""
    try:
        text = json.dumps(value, separators=(",", ":"), allow_nan=False)
    except ValueError as exc:
        raise ValueError(
            "standalone HTML metadata must be finite JSON; found NaN or infinity"
        ) from exc
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _javascript_for_inline_script(source: str) -> str:
    """JavaScript source safe to place in a raw inline <script> element.

    The HTML parser closes script data on `</script` even inside JS strings,
    comments, or regex literals. Escaping the slash preserves JavaScript meaning
    while preventing a bundled client string from terminating the element.
    """
    return source.replace("</", "<\\/")


def _atomic_write_text(path: str | PathLike[str], text: str) -> None:
    """Write text through a same-directory temp file, then replace atomically."""
    target = Path(path)
    parent = target.parent
    fd, tmp_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except Exception:
        if fd != -1:
            with suppress(OSError):
                os.close(fd)
        with suppress(FileNotFoundError):
            tmp_path.unlink()
        raise


def _custom_css_block(custom_css: Optional[str]) -> str:
    """Validate + wrap author-supplied CSS for the standalone <head>.

    This is how `class_names` / Tailwind utility classes become resolvable in
    the browserless standalone export (the widget instead inherits the host
    page's stylesheet). The chrome defaults are zero-specificity `:where()`
    rules, so any rule here wins. The one hazard is a `</style>` breaking out of
    the style element into markup — rejected (whitespace-tolerant, since the
    HTML parser ignores whitespace inside a closing tag)."""
    if custom_css is None:
        return ""
    if not isinstance(custom_css, str):
        raise TypeError("custom_css must be a string")
    if _re.search(r"<\s*/\s*style", custom_css, _re.IGNORECASE) or "<!--" in custom_css:
        raise ValueError("custom_css must not contain a </style> or comment sequence")
    return f"<style>{custom_css}</style>\n"


def to_html(
    fig: "Figure",
    path: Optional[str | PathLike[str]] = None,
    *,
    custom_css: Optional[str] = None,
) -> str:
    """Render `fig` to a standalone interactive HTML string (optionally saved).

    User strings (title, names, labels) ride inside <script>/<title> blocks:
    HTML-sensitive JSON characters are escaped so user text cannot alter the
    script parse state, and the <title> text is entity-escaped.

    `custom_css` injects an author stylesheet into the document <head> so the
    utility classes referenced by `class_names` (e.g. Tailwind) resolve in the
    standalone export; it must not contain a `</style>` breakout sequence."""
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
    client_js = _javascript_for_inline_script(_bundled_js("standalone"))
    title_html = _html.escape(fig.title or "xy")
    doc = f"""<!doctype html>
<html>
<head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{_STANDALONE_CSP}">
<title>{title_html}</title>
<style>
html,body{{margin:0;width:100%;min-height:100%;font-family:system-ui,sans-serif;background:#fff;}}
#chart{{width:100%;}}
</style>
{_custom_css_block(custom_css)}</head>
<body>
<div id="chart"></div>
<script>{client_js}</script>
<script>
  const spec = {spec_js};
  const b64 = "{base64.b64encode(blob).decode("ascii")}";
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);
</script>
</body>
</html>"""
    if path is not None:
        _atomic_write_text(path, doc)
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
    sandbox: bool = True,
) -> bytes:
    """Rasterize a standalone chart HTML string to PNG bytes via headless
    Chromium `--screenshot`. Pure mechanism (no Figure), so it is testable
    without numpy. `scale` is the device-pixel ratio (2 = retina-crisp)."""
    width = _positive_pixel_count(width, "PNG width")
    height = _positive_pixel_count(height, "PNG height")
    scale = _positive_finite_float(scale, "PNG scale")
    time_budget_ms = _positive_pixel_count(time_budget_ms, "PNG time_budget_ms")
    timeout_s = _positive_finite_float(timeout_s, "PNG timeout_s")
    sandbox = _bool_option(sandbox, "PNG sandbox")
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
        args = [
            exe,
            "--headless=new",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            "--use-angle=swiftshader",
            "--enable-unsafe-swiftshader",
            f"--force-device-scale-factor={scale}",
            f"--window-size={int(width)},{int(height)}",
            f"--virtual-time-budget={int(time_budget_ms)}",
            f"--screenshot={shot}",
            page.as_uri(),
        ]
        if not sandbox:
            args.insert(2, "--no-sandbox")
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if not shot.exists():
            first_tail = (proc.stderr or "")[-500:]
            if sandbox:
                retry_args = list(args)
                retry_args.insert(2, "--no-sandbox")
                proc = subprocess.run(
                    retry_args,
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                )
            if not shot.exists():
                tail = (proc.stderr or "")[-500:]
                if sandbox:
                    tail = f"sandboxed launch failed: {first_tail}\nno-sandbox retry failed: {tail}"
                raise RuntimeError(
                    f"Chromium produced no screenshot (exit {proc.returncode}): {tail}"
                )
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
    engine: str = "native",
    chromium: Optional[str] = None,
    sandbox: bool = True,
) -> bytes:
    """Rasterize `fig` to a PNG (bytes, optionally saved).

    `engine="native"` (default) paints the decimated payload with the built-in
    Rust rasterizer — no browser, millisecond export, small indexed PNGs.
    `engine="chromium"` renders the standalone HTML in headless Chromium and
    screenshots it, so the pixels match the interactive WebGL chart exactly
    (needs a Chromium binary; honors `chromium`/`sandbox`). Fluid ("100%") sizes
    fall back to an explicit export size since a raster needs concrete dims."""
    w = _positive_pixel_count(
        width if width is not None else (fig.width if isinstance(fig.width, int) else 800),
        "PNG width",
    )
    h = _positive_pixel_count(
        height if height is not None else (fig.height if isinstance(fig.height, int) else 500),
        "PNG height",
    )
    scale = _positive_finite_float(scale, "PNG scale")
    sandbox = _bool_option(sandbox, "PNG sandbox")
    if engine not in ("native", "chromium"):
        raise ValueError(f"PNG engine must be 'native' or 'chromium', got {engine!r}")
    if engine == "native":
        from . import _raster

        data = _raster.to_png(fig, None, width=w, height=h, scale=scale)
    else:
        doc = to_html(fig)
        data = html_to_png(doc, w, h, scale=scale, chromium=chromium, sandbox=sandbox)
    if path is not None:
        with open(path, "wb") as f:
            f.write(data)
    return data
