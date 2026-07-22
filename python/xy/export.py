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
import warnings
from collections.abc import Iterator
from contextlib import suppress
from enum import StrEnum
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, SupportsFloat, SupportsIndex, cast

if TYPE_CHECKING:
    from ._figure import Figure


class Engine(StrEnum):
    """Static-export engine.

    ``default`` is XY's fast, deterministic native renderer. ``chromium``
    renders the standalone chart with an automatically discovered installed
    Chromium-family browser for browser CSS/WebGL fidelity. ``auto`` picks
    deterministically per format: native for every natively supported format
    (all of them — png/jpeg/webp/svg/pdf), chromium only when the request
    needs a real CSS engine (``custom_css``).
    """

    auto = "auto"
    default = "default"
    chromium = "chromium"


# Warn above this payload size; base64 carries a stated ~33% tax (§29).
EMBED_WARN_BYTES = 64 * 2**20

# The standalone export has no binary comm channel, so §29's "chunked base64"
# fallback applies. The blob is split into 3-byte-aligned slices (except the
# last), so each chunk's base64 has no interior padding and decodes
# independently into a contiguous region of one preallocated buffer — the bytes
# are identical to the source blob, and no single JS string ever approaches
# V8's ~512 MB length cliff (the failure mode that caps a single embedded
# string). 48 MiB is divisible by 3, keeping the alignment invariant trivially.
_B64_CHUNK_BYTES = 48 * 2**20

# Browser-fidelity PNG export shells out to an installed, headless-capable
# browser — no Python browser dependency and no bundled browser runtime.  The
# first adapter is the Chromium family (Chrome, Chromium, Edge, and the smaller
# headless shell), all of which share the command line + CDP surface used here.
# The public enum deliberately selects the fidelity tier rather than exposing
# executable paths; discovery remains an implementation detail.
_BROWSER_ENV = "XY_BROWSER"
_CHROMIUM_ENV = "XY_CHROMIUM"
_BROWSER_NAMES = (
    "chrome-headless-shell",
    "chromium",
    "chromium-browser",
    "chrome",
    "google-chrome",
    "google-chrome-stable",
    "microsoft-edge",
    "microsoft-edge-stable",
    "msedge",
)
_BROWSER_FALLBACKS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Microsoft Edge Beta.app/Contents/MacOS/Microsoft Edge Beta",
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


def _base64_chunks(blob: bytes) -> list[str]:
    """Base64 the payload as 3-byte-aligned chunks (see `_B64_CHUNK_BYTES`).

    Every chunk but the last encodes a multiple of 3 bytes, so its base64 has no
    interior `=` padding and decodes to an exact byte length — letting the client
    reassemble one contiguous buffer without tracking base64 boundaries. A
    memoryview avoids copying the (potentially huge) blob per slice."""
    if not blob:
        return []
    view = memoryview(blob)
    step = _B64_CHUNK_BYTES
    return [base64.b64encode(view[i : i + step]).decode("ascii") for i in range(0, len(view), step)]


# Inline decoder for the chunked base64 payload. Prefers the native Uint8Array
# base64 decoder (baseline across browsers since 2025) and falls back to a tight
# `atob` + `charCodeAt` loop into a preallocated array — far cheaper than
# `Uint8Array.from(atob(s), c => c.charCodeAt(0))`, whose per-element mapper
# dominates decode time at millions of points. Returns one ArrayBuffer whose
# bytes match the source blob exactly, so `spec.columns[i].byte_offset` stays
# valid end-to-end.
_DECODE_B64_JS = (
    "function xyDecodeB64(chunks, total) {"
    "const bytes = new Uint8Array(total); let off = 0;"
    'const native = typeof bytes.setFromBase64 === "function";'
    "for (let i = 0; i < chunks.length; i++) {"
    "const s = chunks[i];"
    "if (native) { off += bytes.subarray(off).setFromBase64(s).written; }"
    "else { const bin = atob(s), n = bin.length;"
    "for (let j = 0; j < n; j++) bytes[off + j] = bin.charCodeAt(j); off += n; }"
    "} return bytes.buffer; }"
)


def _atomic_write_bytes(path: str | PathLike[str], data: bytes) -> None:
    """Write bytes through a same-directory temp file, then replace atomically."""
    target = Path(path)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            fd = -1
            f.write(data)
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


def _standalone_parts(
    fig: "Figure",
    *,
    custom_css: Optional[str] = None,
    animation_progress: Optional[float] = None,
) -> Iterator[str]:
    """Yield one standalone document without first joining its large parts."""
    spec, blob = fig.build_payload()
    if animation_progress is not None:
        progress = float(animation_progress)
        if not math.isfinite(progress) or not 0.0 <= progress <= 1.0:
            raise ValueError("animation progress must be between 0 and 1")
        spec["animation_capture_progress"] = progress
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
    # One <script> block PER chunk: a script element's source is itself a V8
    # string, so folding every chunk into one block would rebuild the very
    # ~512 MB single-string ceiling the chunking removed. Per-block sources
    # stay at ~64 MB regardless of payload size. Chunk text is standard base64
    # (`[A-Za-z0-9+/=]`) — it can hold no `"`, `\`, newline, or `<`, so it is a
    # valid JS string literal verbatim and can never close the <script>. Quote
    # it directly rather than via `json.dumps`, whose full-string escape scan
    # dominated small-chart export cost.
    yield f"""<!doctype html>
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
<script>"""
    yield client_js
    yield """</script>
<script>var __xyChunks = [];</script>
"""
    for chunk in _base64_chunks(blob):
        yield f'<script>__xyChunks.push("{chunk}");</script>\n'
    yield f"""<script>
  {_DECODE_B64_JS}
  const spec = {spec_js};
  const buf = xyDecodeB64(__xyChunks, {len(blob)});
  __xyChunks.length = 0;
  xy.renderStandalone(document.getElementById("chart"), spec, buf);
</script>
</body>
</html>"""


def to_html(
    fig: "Figure",
    path: Optional[str | PathLike[str]] = None,
    *,
    custom_css: Optional[str] = None,
    animation_progress: Optional[float] = None,
) -> str:
    """Render `fig` to a standalone interactive HTML string (optionally saved).

    User strings (title, names, labels) ride inside <script>/<title> blocks:
    HTML-sensitive JSON characters are escaped so user text cannot alter the
    script parse state, and the <title> text is entity-escaped.

    `custom_css` injects an author stylesheet into the document <head> so the
    utility classes referenced by `class_names` (e.g. Tailwind) resolve in the
    standalone export; it must not contain a `</style>` breakout sequence."""
    doc = "".join(
        _standalone_parts(
            fig,
            custom_css=custom_css,
            animation_progress=animation_progress,
        )
    )
    if path is not None:
        _atomic_write_text(path, doc)
    return doc


_NOTEBOOK_DIMENSION_RE = _re.compile(r"^[0-9]+(?:\.[0-9]+)?(?:px|%|vw|vh|rem|em)?$")


def _notebook_dimension(value: object, fallback: int) -> tuple[str, bool]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{max(1, int(value))}px", True
    text = str(value).strip()
    if _NOTEBOOK_DIMENSION_RE.fullmatch(text):
        if text.replace(".", "", 1).isdigit():
            return f"{max(1, int(float(text)))}px", True
        return text, text.endswith("px")
    return f"{fallback}px", True


def notebook_iframe(doc: str, *, width: object, height: object) -> str:
    """Embed a standalone document without leaking its CSS into a notebook.

    Rich HTML display payloads are fragments, even when their value happens to
    contain ``<html>``/``<body>`` tags.  Consequently a notebook frontend may
    apply the standalone document's global selectors to the notebook itself.
    ``srcdoc`` gives the export a real document boundary while preserving the
    self-contained, offline display path.
    """
    source = _html.escape(doc, quote=True)
    return _notebook_iframe_prefix(width, height) + source + '"></iframe>'


def _notebook_iframe_prefix(width: object, height: object) -> str:
    """Opening iframe tag shared by materialized and streaming repr paths."""
    width_css, fixed_width = _notebook_dimension(width, 900)
    height_css, _ = _notebook_dimension(height, 420)
    width_attr = width_css.removesuffix("px")
    height_attr = height_css.removesuffix("px")
    width_style = f"width:100%;max-width:{width_css}" if fixed_width else f"width:{width_css}"
    return (
        '<iframe class="xy-notebook-frame" sandbox="allow-scripts" '
        f'width="{width_attr}" height="{height_attr}" '
        f'style="display:block;{width_style};height:{height_css};margin-left:8px;'
        'border:0;background:transparent" '
        'srcdoc="'
    )


def notebook_figure_iframe(fig: "Figure", *, width: object, height: object) -> str:
    """Build a notebook repr directly into its escaped ``srcdoc`` output.

    Escaping fixed-size slices avoids retaining both a complete standalone
    document and a second complete escaped copy. The returned HTML is byte-for-
    byte identical to ``notebook_iframe(to_html(fig), ...)``.
    """
    parts = [_notebook_iframe_prefix(width, height)]
    escape_chunk = 64 * 1024
    for part in _standalone_parts(fig):
        parts.extend(
            _html.escape(part[start : start + escape_chunk], quote=True)
            for start in range(0, len(part), escape_chunk)
        )
    parts.append('"></iframe>')
    return "".join(parts)


def _installed_browser(candidate: object) -> Optional[str]:
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    text = os.path.expandvars(os.path.expanduser(candidate.strip()))
    if Path(text).exists():
        return text
    return shutil.which(text)


def find_browser(explicit: Optional[str] = None) -> Optional[str]:
    """Locate a supported installed browser executable, or return ``None``.

    ``None`` and ``"auto"`` search ``XY_BROWSER``, the legacy
    ``XY_CHROMIUM`` variable, ``PATH``, and common application locations.
    Any other value is treated as an explicit path or executable name and is
    not silently replaced with a different installed browser when missing.
    """
    if explicit not in (None, "auto"):
        return _installed_browser(explicit)
    for env_name in (_BROWSER_ENV, _CHROMIUM_ENV):
        configured = os.environ.get(env_name)
        if configured:
            return _installed_browser(configured)
    for name in _BROWSER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    fallbacks = list(_BROWSER_FALLBACKS)
    for root_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(root_name)
        if not root:
            continue
        fallbacks.extend(
            (
                str(Path(root) / "Google/Chrome/Application/chrome.exe"),
                str(Path(root) / "Microsoft/Edge/Application/msedge.exe"),
            )
        )
    for cand in fallbacks:
        if Path(cand).exists():
            return cand
    return None


def find_chromium(explicit: Optional[str] = None) -> Optional[str]:
    """Compatibility alias for :func:`find_browser`."""
    return find_browser(explicit)


def _png_engine(engine: object, label: str = "PNG") -> str:
    if isinstance(engine, Engine):
        return "native" if engine is Engine.default else "browser"
    if engine == "native":
        warnings.warn(
            'engine="native" is deprecated; use engine=Engine.default instead',
            DeprecationWarning,
            stacklevel=3,
        )
        return "native"
    if engine in ("chromium", "browser"):
        warnings.warn(
            "string export engines are deprecated; use engine=Engine.chromium instead",
            DeprecationWarning,
            stacklevel=3,
        )
        return "browser"
    raise ValueError(f"{label} engine must be Engine.default or Engine.chromium, got {engine!r}")


def _gl_option(value: object) -> str:
    if value not in ("software", "hardware"):
        raise ValueError(f"PNG gl must be 'software' or 'hardware', got {value!r}")
    return cast(str, value)


def html_to_png(
    html: str,
    width: int,
    height: int,
    *,
    scale: float = 2.0,
    time_budget_ms: int = 4000,
    timeout_s: float = 120.0,
    sandbox: bool = True,
    gl: str = "software",
) -> bytes:
    """Rasterize standalone chart HTML to PNG with an installed headless browser.

    The current adapter supports the Chromium family
    (Chrome, Chromium, Edge, and chrome-headless-shell). Pure mechanism (no
    Figure), so it is testable without numpy. `scale` is the device-pixel
    ratio (2 = retina-crisp).

    `gl` picks the WebGL backend: "software" (default) pins SwiftShader for
    deterministic pixels on any machine (including GPU-less CI); "hardware"
    lets Chromium use the real GPU — much faster on large direct-mode payloads,
    at the cost of driver-dependent rasterization."""
    width = _positive_pixel_count(width, "PNG width")
    height = _positive_pixel_count(height, "PNG height")
    scale = _positive_finite_float(scale, "PNG scale")
    time_budget_ms = _positive_pixel_count(time_budget_ms, "PNG time_budget_ms")
    timeout_s = _positive_finite_float(timeout_s, "PNG timeout_s")
    sandbox = _bool_option(sandbox, "PNG sandbox")
    gl = _gl_option(gl)
    exe = find_browser()
    if exe is None:
        raise RuntimeError(
            "browser PNG export needs a supported Chrome/Chromium/Edge executable "
            f"and none was found. Set ${_BROWSER_ENV} to its executable path "
            "or install a supported browser. HTML export (to_html) needs nothing extra."
        )
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "chart.html"
        page.write_text(html, encoding="utf-8")
        shot = Path(td) / "out.png"
        gl_flags = (
            ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] if gl == "software" else []
        )
        args = [
            exe,
            "--headless=new",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            *gl_flags,
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


def write_images(
    figs: Optional[list[Any]] = None,
    paths: Optional[list[str | PathLike[str]]] = None,
    *,
    figures: Optional[list[Any]] = None,
    files: Optional[list[str | PathLike[str]]] = None,
    formats: Optional[str | list[str]] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    scale: Optional[float] = None,
    background: Optional[str] = None,
    engine: Engine | str = Engine.auto,
    quality: Optional[int] = None,
    optimize: bool = False,
    custom_css: Optional[str] = None,
    sandbox: bool = True,
    gl: str = "software",
) -> list[bytes]:
    """Export many figures through ONE amortized pipeline (mixed formats OK).

    Each file's format is inferred from its extension (`formats=` overrides:
    one string for all files or one per file) across the full unified matrix —
    PNG/JPEG/WebP/SVG/PDF plus standalone HTML. Native exports simply loop the
    millisecond-fast, browser-free renderers; every Chromium-resolved export
    in the batch shares a single persistent browser session (CDP;
    `_chromium.py`) instead of paying ~1-2 s of startup per figure — the
    classic batch-export trap. `figures=`/`files=` are keyword aliases for
    the positional pair, and composed charts (anything with a `.figure()`)
    are accepted directly — a chart's `export_config` defaults fill any
    omitted width/height/scale/background/quality for that chart's files,
    exactly as in `Chart.to_image`. Writes are atomic per file; on error,
    files already exported remain. Other options match `to_image`; quality
    applies to JPEG and Chromium WebP and is ignored by the other formats
    (native WebP stays lossless), so mixed batches stay ergonomic."""
    if figures is not None:
        if figs is not None:
            raise ValueError("pass figs positionally or figures=, not both")
        figs = figures
    if files is not None:
        if paths is not None:
            raise ValueError("pass paths positionally or files=, not both")
        paths = files
    if figs is None or paths is None:
        raise ValueError("write_images needs both figures and files")
    if len(figs) != len(paths):
        raise ValueError(f"write_images got {len(figs)} figures but {len(paths)} paths")
    if isinstance(formats, str):
        fmts = [_normalize_format(formats, allow_html=True)] * len(paths)
    elif formats is not None:
        if len(formats) != len(paths):
            raise ValueError(f"write_images got {len(formats)} formats but {len(paths)} paths")
        fmts = [_normalize_format(f, allow_html=True) for f in formats]
    else:
        fmts = [_infer_format(p) for p in paths]
    if scale is not None:
        scale = _positive_finite_float(scale, "export scale")
    if quality is not None:
        # Range-check once up front; per-file policy below decides where the
        # value actually applies (JPEG + Chromium WebP).
        _validated_quality(quality, "jpeg", "native")
    optimize = _bool_option(optimize, "export optimize")
    sandbox = _bool_option(sandbox, "export sandbox")
    gl = _gl_option(gl)

    # Resolve the whole plan before any I/O so bad arguments fail the batch
    # up front instead of after a partial export. Chart wrappers are kept
    # long enough to resolve their declarative export_config defaults; only
    # then are they compiled down to figures.
    plan: list[
        tuple["Figure", str | PathLike[str], str, str, dict[str, Any], Optional[int], Optional[str]]
    ] = []
    for obj, path, fmt in zip(figs, paths, fmts, strict=True):
        fig = obj.figure() if callable(getattr(obj, "figure", None)) else obj
        if fmt == "html":
            plan.append((fig, path, fmt, "html", {}, None, None))
            continue
        resolved = _resolve_image_engine(engine, fmt, custom_css)
        if callable(getattr(obj, "_export_defaults", None)):
            settings = obj._export_defaults(
                fmt,
                width,
                height,
                scale,
                background,
                quality,
                lossy_webp=resolved == "browser",
            )
        else:
            settings = {
                "width": width,
                "height": height,
                "scale": scale if scale is not None else 2.0,
                "background": background,
                "quality": quality,
            }
        file_quality = (
            _validated_quality(settings["quality"], fmt, resolved)
            if fmt == "jpeg" or (fmt == "webp" and resolved == "browser")
            else None
        )
        try:
            file_background = _validated_background(settings["background"], fmt)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from None
        plan.append((fig, path, fmt, resolved, settings, file_quality, file_background))

    out: list[bytes] = []
    session: Optional[Any] = None
    try:
        for fig, path, fmt, resolved, settings, file_quality, file_background in plan:
            if resolved == "html":
                out.append(to_html(fig, path, custom_css=custom_css).encode("utf-8"))
                continue
            w, h = _export_dimensions(fig, settings["width"], settings["height"])
            file_scale = _positive_finite_float(settings["scale"], "export scale")
            if resolved == "native":
                data = _native_image(
                    fig,
                    fmt,
                    width=w,
                    height=h,
                    scale=file_scale,
                    background=file_background,
                    quality=file_quality,
                    optimize=optimize,
                )
            else:
                if session is None:
                    session = _browser_session(gl=gl, sandbox=sandbox)
                data = _browser_image(
                    session,
                    fig,
                    fmt,
                    width=w,
                    height=h,
                    scale=file_scale,
                    background=file_background,
                    quality=file_quality,
                    custom_css=custom_css,
                )
            _atomic_write_bytes(path, data)
            out.append(data)
    finally:
        if session is not None:
            session.close()
    return out


def to_png(
    fig: "Figure",
    path: Optional[str | PathLike[str]] = None,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    scale: float = 2.0,
    engine: Engine = Engine.default,
    optimize: bool = False,
    custom_css: Optional[str] = None,
    sandbox: bool = True,
    gl: str = "software",
) -> bytes:
    """Rasterize `fig` to a PNG (bytes, optionally saved).

    `engine=Engine.default` paints the decimated payload with the built-in
    Rust rasterizer — no browser and millisecond export. Pass
    ``optimize=True`` to trade latency for the smaller indexed/deflate output.
    `engine=Engine.chromium` renders the standalone HTML in an installed
    browser and screenshots it, so CSS, fonts, and WebGL use that browser's
    implementation. It automatically discovers Chrome, Chromium, Edge, or
    `chrome-headless-shell` via `XY_BROWSER`, PATH, and common install locations,
    and honors `sandbox`/`gl` (see `html_to_png`). `custom_css` injects an
    author stylesheet into that browser document and is rejected by the native
    engine. Former string engine values remain deprecated aliases.
    Fluid ("100%") sizes fall back to an explicit export size since a raster
    needs concrete dims."""
    w = _positive_pixel_count(
        width if width is not None else (fig.width if isinstance(fig.width, int) else 800),
        "PNG width",
    )
    h = _positive_pixel_count(
        height if height is not None else (fig.height if isinstance(fig.height, int) else 500),
        "PNG height",
    )
    scale = _positive_finite_float(scale, "PNG scale")
    optimize = _bool_option(optimize, "PNG optimize")
    sandbox = _bool_option(sandbox, "PNG sandbox")
    resolved_engine = _png_engine(engine)
    if resolved_engine == "native":
        if custom_css is not None:
            raise ValueError("custom_css requires engine=Engine.chromium")
        from . import _raster

        data = _raster.to_png(fig, None, width=w, height=h, scale=scale, fast=not optimize)
    else:
        doc = to_html(fig, custom_css=custom_css, animation_progress=1.0)
        data = html_to_png(
            doc,
            w,
            h,
            scale=scale,
            sandbox=sandbox,
            gl=gl,
        )
    if path is not None:
        with open(path, "wb") as f:
            f.write(data)
    return data


# ---------------------------------------------------------------------------
# Unified format-selecting export (ENG-10447): one API across PNG/JPEG/WebP/
# SVG/PDF (+ HTML routing in `write_image`), with deterministic per-format
# engine selection and a shared background policy. The per-format methods
# above (`to_png`, `to_html`, `_svg.to_svg`) remain the compatibility surface.
# ---------------------------------------------------------------------------

# Formats `to_image` can produce. HTML is deliberately not an image format —
# `write_image("chart.html")` routes to `to_html`, and `to_image("html")`
# points there — matching the issue's "interactive/data, not image" split.
IMAGE_FORMATS = ("png", "jpeg", "webp", "svg", "pdf")
_FORMAT_ALIASES = {"jpg": "jpeg"}
_LOSSY_QUALITY_FORMATS = ("jpeg", "webp")
_DEFAULT_QUALITY = 90

# Conservative CSS <color> shape for export backgrounds: enough for every
# color syntax (named, hex, rgb[a]/hsl[a]/oklch) while excluding anything able
# to escape a style declaration it is interpolated into ({}, ;, quotes, <).
_BACKGROUND_RE = _re.compile(r"^[A-Za-z0-9#().,%/\s+-]+$")


def _normalize_format(value: object, *, allow_html: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"format must be one of {IMAGE_FORMATS}, got {value!r}")
    fmt = _FORMAT_ALIASES.get(value.lower().lstrip("."), value.lower().lstrip("."))
    if fmt == "html":
        if allow_html:
            return fmt
        raise ValueError(
            "html is not an image format — use to_html() (or write_image('chart.html'), "
            "which routes there)"
        )
    if fmt not in IMAGE_FORMATS:
        raise ValueError(f"format must be one of {IMAGE_FORMATS} (or 'jpg'), got {value!r}")
    return fmt


def _infer_format(path: str | PathLike[str]) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix in ("html", "htm"):
        return "html"
    if not suffix:
        raise ValueError(
            f"cannot infer an export format from {str(path)!r}: add a file extension "
            f"({', '.join('.' + f for f in (*IMAGE_FORMATS, 'jpg', 'html'))}) "
            "or pass format= explicitly"
        )
    try:
        return _normalize_format(suffix, allow_html=True)
    except ValueError:
        raise ValueError(
            f"cannot infer an export format from {str(path)!r}: unknown extension "
            f"{'.' + suffix!r}. Supported: "
            f"{', '.join('.' + f for f in (*IMAGE_FORMATS, 'jpg', 'html'))}, "
            "or pass format= explicitly"
        ) from None


def _resolve_image_engine(engine: object, fmt: str, custom_css: Optional[str]) -> str:
    """Deterministic engine selection: -> "native" | "browser".

    auto => native for every format (they are all natively supported;
    browser-free is the architectural fast path), except that `custom_css`
    forces chromium since utility-class CSS needs a real CSS engine. SVG is
    native-only: a screenshotting browser cannot emit vector SVG.
    """
    if engine in (Engine.auto, "auto", None):
        resolved = "browser" if custom_css is not None else "native"
    else:
        resolved = _png_engine(engine, fmt.upper())
    if resolved == "browser" and fmt == "svg":
        raise ValueError(
            "SVG export is native-only (a browser screenshot cannot produce vector "
            "SVG); drop engine=Engine.chromium and custom_css"
        )
    if resolved == "native" and custom_css is not None:
        raise ValueError("custom_css requires engine=Engine.chromium")
    return resolved


def _validated_quality(quality: object, fmt: str, resolved_engine: str) -> Optional[int]:
    if quality is None:
        return _DEFAULT_QUALITY if fmt in _LOSSY_QUALITY_FORMATS else None
    if fmt not in _LOSSY_QUALITY_FORMATS:
        raise ValueError(f"quality applies to {'/'.join(_LOSSY_QUALITY_FORMATS)}, not {fmt}")
    if isinstance(quality, bool) or not isinstance(quality, numbers.Integral):
        raise ValueError(f"quality must be an integer in 1..100, got {quality!r}")
    out = int(quality)
    if not 1 <= out <= 100:
        raise ValueError(f"quality must be an integer in 1..100, got {out}")
    if fmt == "webp" and resolved_engine == "native":
        raise ValueError(
            "native WebP export is always lossless (deterministic policy); "
            "drop quality=, or use engine=Engine.chromium for lossy WebP"
        )
    return out


def _validated_background(background: object, fmt: str) -> Optional[str]:
    """Shared background policy (documented in docs/export.md).

    None ("auto") keeps each renderer's default backdrop: opaque white for
    raster/browser output, transparent for SVG/PDF vector output. A CSS color
    paints one canvas backdrop consistently across formats. "transparent" is
    valid everywhere alpha exists — JPEG has no alpha channel, so it is
    rejected there rather than silently flattened."""
    if background in (None, "auto"):
        return None
    if not isinstance(background, str) or not background.strip():
        raise ValueError(f"background must be a CSS color or 'transparent', got {background!r}")
    value = background.strip()
    if not _BACKGROUND_RE.fullmatch(value):
        raise ValueError(f"background is not a safe CSS color: {background!r}")
    if value.lower() in ("transparent", "none"):
        if fmt == "jpeg":
            raise ValueError(
                "JPEG has no alpha channel; pass an opaque background= (default white) "
                "or export PNG/WebP for transparency"
            )
        return "transparent"
    return value


def _export_dimensions(
    fig: "Figure", width: Optional[int], height: Optional[int]
) -> tuple[int, int]:
    w = _positive_pixel_count(
        width if width is not None else (fig.width if isinstance(fig.width, int) else 800),
        "export width",
    )
    h = _positive_pixel_count(
        height if height is not None else (fig.height if isinstance(fig.height, int) else 500),
        "export height",
    )
    return w, h


def _flatten_alpha(rgba: "Any") -> "Any":
    """Composite leftover alpha over white — the JPEG determinism backstop."""
    import numpy as np

    alpha = rgba[..., 3:4].astype(np.uint16)
    rgb = (rgba[..., :3].astype(np.uint16) * alpha + 255 * (255 - alpha) + 127) // 255
    out = np.empty_like(rgba)
    out[..., :3] = rgb.astype(np.uint8)
    out[..., 3] = 255
    return out


def _background_css(background: Optional[str]) -> str:
    """Page CSS for the export `background=` override in browser capture.

    Mirrors `_svg.apply_export_background`: the override replaces the whole
    painted backdrop, so it must beat the chart root's inline theme background
    and the `--chart-bg` plot token the render client reads from computed
    style (`!important` outranks inline styles and the token becomes
    transparent so translucent overrides composite exactly once)."""
    if background is None:
        return ""
    return (
        f"html,body{{background:{background} !important;}}"
        f".xy{{background:{background} !important;--chart-bg:transparent !important;}}"
    )


def _browser_html(fig: "Figure", custom_css: Optional[str], background: Optional[str]) -> str:
    """Standalone document for browser capture, with the export background
    override injected as page CSS (validated by `_validated_background`)."""
    css = _background_css(background) + (custom_css or "")
    return to_html(fig, custom_css=css or None, animation_progress=1.0)


def _browser_session(*, gl: str, sandbox: bool) -> "Any":
    """One launched ChromiumSession, mirroring `html_to_png`'s sandbox retry."""
    exe = find_browser()
    if exe is None:
        raise RuntimeError(
            "browser image export needs a supported Chrome/Chromium/Edge executable "
            f"and none was found. Set ${_BROWSER_ENV} to its executable path "
            "or install a supported browser. Native export (engine=Engine.default) "
            "and HTML export need nothing extra."
        )
    from ._chromium import ChromiumError, ChromiumSession

    try:
        return ChromiumSession(exe, gl=gl, sandbox=sandbox)
    except ChromiumError:
        if not sandbox:
            raise
        return ChromiumSession(exe, gl=gl, sandbox=False)


def _native_image(
    fig: "Figure",
    fmt: str,
    *,
    width: int,
    height: int,
    scale: float,
    background: Optional[str],
    quality: Optional[int],
    optimize: bool,
) -> bytes:
    from . import _raster

    if fmt == "png":
        return _raster.to_png(
            fig,
            None,
            width=width,
            height=height,
            scale=scale,
            fast=not optimize,
            background=background,
        )
    if fmt == "svg":
        from . import _svg

        return _svg.to_svg(fig, None, width=width, height=height, background=background).encode(
            "utf-8"
        )
    if fmt == "pdf":
        from . import _pdf, _svg

        svg = _svg.to_svg(fig, None, width=width, height=height, background=background)
        return _pdf.svg_to_pdf(svg)
    rgba = _raster.to_rgba(fig, width=width, height=height, scale=scale, background=background)
    if fmt == "jpeg":
        from . import _jpeg

        return _jpeg.encode(_flatten_alpha(rgba), quality=quality or _DEFAULT_QUALITY)
    if fmt == "webp":
        from . import _webp

        return _webp.encode(rgba)
    raise AssertionError(f"unreachable native format {fmt!r}")


def _browser_image(
    session: "Any",
    fig: "Figure",
    fmt: str,
    *,
    width: int,
    height: int,
    scale: float,
    background: Optional[str],
    quality: Optional[int],
    custom_css: Optional[str],
) -> bytes:
    doc = _browser_html(fig, custom_css, background)
    if fmt == "pdf":
        return session.render_pdf(doc, width, height)
    return session.render_image(
        doc,
        width,
        height,
        format=fmt,
        scale=scale,
        quality=quality,
        transparent=background == "transparent",
    )


def to_image(
    fig: "Figure",
    format: str = "png",
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    scale: float = 2.0,
    background: Optional[str] = None,
    engine: Engine | str = Engine.auto,
    quality: Optional[int] = None,
    optimize: bool = False,
    custom_css: Optional[str] = None,
    sandbox: bool = True,
    gl: str = "software",
) -> bytes:
    """Render `fig` to image bytes in the requested `format`.

    Formats: "png", "jpeg"/"jpg", "webp", "svg", "pdf" (SVG returns UTF-8
    bytes; for interactive HTML use `to_html`). `engine=Engine.auto` (default)
    is deterministic: every format uses the browser-free native path unless
    `custom_css` forces Chromium; `engine=Engine.chromium` renders the
    standalone HTML in an installed browser for CSS/WebGL fidelity (all
    formats except SVG, which is native-only). Native WebP is lossless;
    `quality` (1-100, default 90) applies to JPEG and to Chromium's lossy
    WebP. `background` is "auto" per-format, a CSS color, or "transparent"
    (rejected for JPEG). `scale` is the device-pixel-ratio for raster output
    and is ignored by the vector formats (SVG/PDF are resolution-independent).
    PDF keeps text/axes/marks as vectors; density and heatmap layers embed as
    bounded rasters (the documented hybrid-vector policy)."""
    fmt = _normalize_format(format)
    resolved_engine = _resolve_image_engine(engine, fmt, custom_css)
    quality = _validated_quality(quality, fmt, resolved_engine)
    background = _validated_background(background, fmt)
    w, h = _export_dimensions(fig, width, height)
    scale = _positive_finite_float(scale, "export scale")
    optimize = _bool_option(optimize, "export optimize")
    sandbox = _bool_option(sandbox, "export sandbox")
    gl = _gl_option(gl)
    if resolved_engine == "native":
        return _native_image(
            fig,
            fmt,
            width=w,
            height=h,
            scale=scale,
            background=background,
            quality=quality,
            optimize=optimize,
        )
    with _browser_session(gl=gl, sandbox=sandbox) as session:
        return _browser_image(
            session,
            fig,
            fmt,
            width=w,
            height=h,
            scale=scale,
            background=background,
            quality=quality,
            custom_css=custom_css,
        )


def write_image(
    fig: "Figure",
    path: str | PathLike[str],
    *,
    format: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    scale: float = 2.0,
    background: Optional[str] = None,
    engine: Engine | str = Engine.auto,
    quality: Optional[int] = None,
    optimize: bool = False,
    custom_css: Optional[str] = None,
    sandbox: bool = True,
    gl: str = "software",
) -> bytes:
    """Export `fig` to `path`, inferring the format from the extension.

    `format=` overrides inference (required when the path has no/unknown
    extension). Writes are atomic: a same-directory temp file is fsynced then
    renamed over the target, so readers never observe a partial image.
    ".html" routes to `to_html` (interactive export; raster-only options are
    rejected there). Returns the written bytes. All other options match
    `to_image`."""
    fmt = _normalize_format(format, allow_html=True) if format is not None else _infer_format(path)
    if fmt == "html":
        rejected = [
            name
            for name, value, default in (
                ("width", width, None),
                ("height", height, None),
                ("scale", scale, 2.0),
                ("background", background, None),
                ("quality", quality, None),
                ("optimize", optimize, False),
            )
            if value != default
        ]
        if engine not in (Engine.auto, "auto"):
            rejected.append("engine")
        if rejected:
            raise ValueError(
                f"HTML export is interactive and ignores {', '.join(sorted(rejected))}; "
                "drop them or export an image format"
            )
        doc = to_html(fig, path, custom_css=custom_css)
        return doc.encode("utf-8")
    data = to_image(
        fig,
        fmt,
        width=width,
        height=height,
        scale=scale,
        background=background,
        engine=engine,
        quality=quality,
        optimize=optimize,
        custom_css=custom_css,
        sandbox=sandbox,
        gl=gl,
    )
    _atomic_write_bytes(path, data)
    return data
