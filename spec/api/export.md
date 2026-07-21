# Static export

How a figure becomes bytes. One unified entry point across five image formats,
a deterministic engine choice, and a browser-free default path. The renderers
consume the same decimated wire payload the browser client consumes
(`build_payload`), so export is **screen-bounded**: source point count does not
enter the output size. Styling fidelity and the documented static-render
approximations live in [`styling.md`](styling.md); this document is the API and
routing contract.

## 1. Public surface

| Entry point | Location | Notes |
|---|---|---|
| `Figure.to_image(format="png", ...)` | `python/xy/_figure.py:1310` | bytes |
| `Figure.write_image(path, format=None, ...)` | `python/xy/_figure.py:1346` | atomic write, extension-inferred |
| `xy.export.to_image(fig, ...)` | `python/xy/export.py:1006` | the implementation both methods delegate to |
| `xy.export.write_image(fig, path, ...)` | `python/xy/export.py:1069` | |
| `xy.write_images(figs, paths, ...)` | `python/xy/export.py:533` | batch, §8 |
| `xy.export_config(...)` | `python/xy/components.py:2301` | declarative defaults, no I/O |
| `xy.Engine` | `python/xy/export.py:27` | §3 |

`to_image` / `write_image` are **methods**, not package-level functions:
`xy.__init__` re-exports only `Engine`, `export_config`, and `write_images`
from the export module. Reach the free functions as `xy.export.to_image(fig,
...)`.

`Chart` mirrors both methods (`components.py:3014`, `components.py:3054`) and
adds one behavior the `Figure` methods do not have: omitted
`width`/`height`/`scale`/`background`/`quality` fall back to the chart's
`export_config` via `_export_defaults` (`components.py:2981`). `FacetChart`
(`components.py:3740`, `components.py:3767`) and `FacetGrid` (`facets.py:354`,
`facets.py:430`) mirror the same format matrix but expose no `width`/`height`
and no `export_config` defaulting — grid geometry is fixed by its panels.

Legacy per-format surfaces remain: `to_html` (interactive standalone document),
`Figure.to_png` (`engine=Engine.default` by default), `_svg.to_svg` (carries
`id_prefix=` for composing several exports into one document). `to_png` routes
through `_png_engine`, which has no `auto` case — it maps any `Engine` that is
not `Engine.default` to the browser, so `Engine.auto` there means Chromium, not
"choose". Use `to_image` when you want the `auto` policy.

`ExportConfig` is pure description. Beyond seeding the Python defaults above it
governs the client modebar's download menu (formats and order, filename
basename); `pdf` and `html` are accepted in `formats=` but are Python-side only
and are skipped in the browser menu (`js/src/53_interaction.js:1020-1038`, where
`EXPORT_ITEMS` enumerates only png/jpeg/webp/svg/csv and the build loop drops any
configured name with no entry). With no `export` spec the menu falls back to
`["png", "svg", "csv"]`; an explicit empty list hides the download items.

There is no Reflex-side export API. `python/reflex-xy/` renders kernel-lessly in
the browser; export runs on the composed chart object in Python.

## 2. Formats and backends

`IMAGE_FORMATS = ("png", "jpeg", "webp", "svg", "pdf")`, with `jpg` aliased to
`jpeg`. HTML is deliberately not an image format: `to_image("html")` raises,
while `write_image("chart.html")` routes to `to_html`, rejecting every
raster-only option that was passed non-default.

| Format | Native backend | Chromium backend |
|---|---|---|
| PNG | `_raster.to_png` → Rust rasterizer (`src/raster.rs`), encoded by the fused Rust path or `_png.encode` | `Page.captureScreenshot` |
| JPEG | `_raster.to_rgba` → `_jpeg.encode` (pure numpy/stdlib baseline JFIF, 4:4:4) | `Page.captureScreenshot` |
| WebP | `_raster.to_rgba` → `_webp.encode` (pure numpy/stdlib VP8L, **lossless only**) | `Page.captureScreenshot` (lossy) |
| SVG | `_svg.to_svg` (pure Python renderer over the wire payload) | none — SVG is native-only |
| PDF | `_svg.to_svg` → `_pdf.svg_to_pdf` (closed SVG subset → single-page vector PDF) | `Page.printToPDF` |

`_png.encode` auto-selects an indexed-palette PNG (color type 3 + `tRNS`) when
the image has ≤256 distinct RGBA colors. `optimize=True` selects this
size-oriented path; `optimize=False` (default) takes the fused Rust encode.

`_pdf.py` accepts only the SVG that `_svg.py` emits and raises
`ValueError("unsupported SVG feature: ...")` on anything else, so generator
drift fails loudly rather than rendering wrong. Text stays text (base-14
Helvetica, WinAnsiEncoding, `?` for out-of-range characters); density and
heatmap layers embed as bounded rasters.

`quality` (1–100, default 90) applies to JPEG and to **Chromium** WebP.
Requesting `quality` for native WebP is an error, not a silent no-op — the
native encoder is lossless by policy (`_validated_quality`).

## 3. Engine selection

```
Engine.auto      # default for to_image/write_image/write_images
Engine.default   # native (browser-free)
Engine.chromium  # installed Chrome/Chromium/Edge/chrome-headless-shell
```

`_resolve_image_engine` (`export.py:800`) resolves to `"native"` or `"browser"`:

- `auto` → **native for every format**. Every format is natively supported, so
  the browser-free path is always the fast path. Size, point count, and trace
  count do not enter this decision.
- `auto` + `custom_css is not None` → **browser**. Utility-class CSS needs a
  real cascade; the native renderers have no CSS engine.
- `native` + `custom_css` → `ValueError`.
- `browser` + `svg` → `ValueError` (a screenshot cannot produce vector SVG).
- Deprecated string values `"native"`, `"chromium"`, `"browser"` still resolve,
  with a `DeprecationWarning` (`_png_engine`).

Browser discovery (`find_browser`) searches `XY_BROWSER`, the legacy
`XY_CHROMIUM`, `PATH` over nine known executable names, then platform install
locations. An explicit non-`"auto"` value is treated as a path or executable
name and is never silently replaced with a different browser. With no browser
found, browser-resolved export raises `RuntimeError` naming `XY_BROWSER` — it
does **not** fall back to native, because the caller asked for browser fidelity
(or passed `custom_css`, which native cannot honor).

## 4. Determinism

Native export is deterministic: `to_image(fig, fmt) == to_image(fig, fmt)` for
all five formats (`tests/test_image_export.py:80`). No wall-clock stamps enter
any output — `_svg.py`'s `datetime` use is time-axis tick math on data values in
UTC, and `_pdf.py` writes no timestamps or generated ids, with stable object
numbering and a byte-accurate xref table.

Browser export is deterministic only to the extent the browser is. `gl="software"`
(the default) pins SwiftShader so rasterization does not depend on the host GPU;
`gl="hardware"` trades that for speed on large direct-mode payloads.

## 5. Dimensions and scale

`_export_dimensions` resolves `width`/`height` from the explicit arguments, else
the figure's own integer size, else `800×500` — a fluid `"100%"` figure has no
concrete size, and a raster needs one. Values must be positive integer pixel
counts.

`scale` is the device-pixel ratio for raster output (default `2.0`): native
rasters multiply canvas pixels, Chromium sets `deviceScaleFactor`. It is ignored
by SVG and PDF, which are resolution-independent — `render_pdf` pins
`deviceScaleFactor: 1.0` and maps the CSS pixel box at 96 px/in ↔ 72 pt/in.

## 6. Background, and the theme-parity gap

`_validated_background` is the shared policy. `None`/`"auto"` keeps each
renderer's default backdrop — opaque white for raster and browser output,
transparent for SVG and PDF. A CSS color (validated against a conservative
`<color>` shape that cannot escape the declaration it is interpolated into)
paints one backdrop consistently across formats. `"transparent"` is valid
wherever alpha exists and is **rejected for JPEG**, which has no alpha channel,
rather than silently flattened.

An explicit background replaces the *entire* painted backdrop — canvas underlay,
`theme(background=)` figure patch, and the `--chart-bg` plot fill — so the
requested color is what shows regardless of chart theme
(`_svg.apply_export_background`, mirrored for browser capture by
`_background_css`, which needs `!important` to beat the root's inline theme
style).

**Open gap: screen/export theme parity.** Kernel-side export resolves color
tokens statically from `spec["dom"]["style"]` — the tokens the chart declared in
Python (`_svg._resolve_static_css_vars`). The live client instead reads
*computed* CSS off the chart root (`readTheme`, `js/src/20_theme.js:51`) and
re-reads it on scheme change or a class mutation via `refreshTheme()`
(`js/src/50_chartview.js:4037`). That refresh is **local to the browser**: no
theme snapshot ever travels back. The eight client→kernel request types are
enumerated exhaustively in [wire-protocol.md](../design/wire-protocol.md) §2, and
their fields are view geometry, screen dimensions, trace/vertex indices,
sequence counters, and a `source` label. None of them carries style.

The consequence is concrete. When a theme comes from the host page (an app
stylesheet, a `.dark` class on an ancestor, a `prefers-color-scheme` flip) the
kernel does not know about it, and `fig.to_image(...)` exports the Python-declared
theme, not what the user is looking at. Themes declared through `xy.theme(...)`
or the chart's own `style` do export faithfully, and the *client-side* modebar
download does match the screen — it snapshots the computed `--chart-*` tokens
(`styling.md` § Standalone HTML). Do not read the client-side match as
end-to-end parity: the two download paths can disagree on the same chart.

Closing this requires a theme snapshot on the comm channel and a bump of the
message contract; nothing in the current protocol carries it.

## 7. The `--no-sandbox` auto-fallback

Chromium launches sandboxed by default. Both browser paths silently downgrade on
failure:

- `html_to_png` (`export.py:509-526`): if the sandboxed run produces no
  screenshot, it rebuilds the argv with `--no-sandbox` inserted and re-runs
  before raising. The final error reports both attempts.
- `_browser_session` (`export.py:926-931`): retries
  `ChromiumSession(..., sandbox=False)` on `ChromiumError`.

So `--no-sandbox` can appear without the caller requesting it, on input that
`html_to_png` accepts as arbitrary HTML. This is a known, accepted residual risk
taken to keep CI and container rasterization working where the sandbox cannot
initialize — see [XY-SEC-2026-03 and its 2026-07-20 status
note](../process/security-audit-2026-07-06.md#status-as-of-2026-07-20-xy-sec-2026-03). The
pending follow-up is to make the fallback opt-in, or at minimum warn, so a
sandbox loss is observable. `sandbox=False` remains the explicit escape hatch
for trusted HTML.

## 8. Batch export

`write_images(figs, paths, ...)` exports many figures — mixed formats included —
through one amortized pipeline. Per-file format comes from the path extension,
or from `formats=` (one string for all, or one per path). `figures=`/`files=`
are keyword aliases for the positional pair, and composed charts (anything with
a `.figure()`) are accepted directly, with their `export_config` defaults
filling that chart's omitted options.

Two properties are the point of the API:

- **Plan-then-write.** The whole plan — engine resolution, quality, background,
  per-chart defaults — is resolved before any I/O, so a bad argument fails the
  batch up front instead of after a partial export.
- **One browser.** Every browser-resolved file in the batch shares a single
  persistent `ChromiumSession` over CDP (`_chromium.py`) instead of paying
  browser startup per figure. The session is opened lazily on the first
  browser-resolved file and closed in a `finally`. Native files never launch a
  browser at all.

Writes are atomic per file (same-directory temp file, fsync, `os.replace`), so a
reader never observes a partial image. Failure mid-batch is not transactional:
files already written stay on disk. The return value is the list of written
byte strings, in input order.
