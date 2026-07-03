# fastcharts

A faster charting engine, per the design dossier in
[`docs/design-dossier.md`](docs/design-dossier.md): **cost scales with pixels on
screen, not points in the dataset.** Plotly's ceilings are removed by four
changes — GPU rendering (not one SVG node per point), binary columnar transport
(not JSON), a native Rust core in the Python process (not main-thread compute),
and a multi-tier level-of-detail system that never ships or draws more
primitives than the screen can show.

**Status: Phase 0 complete + full scatter chart** (Tier-0 direct through Tier-2
density, per the dossier's §5/§11 scatter contract).

Two APIs over one engine — pick per taste; both render in Jupyter / VS Code /
Colab / Marimo via anywidget and export to standalone HTML.

**Composition API** (declarative, Reflex-flavored — but with no Reflex
dependency): a chart container with mark + axis children, snake_case props,
`data=` + column names, and `on_*` event props.

```python
import fastcharts as fc

fc.scatter_chart(
    fc.scatter(x="gdp", y="life", color="continent", size="pop", data=df),
    fc.x_axis(label="GDP per capita"),
    fc.y_axis(label="life expectancy"),
    fc.legend(),
    title="Gapminder",
    on_hover=lambda row: print(row),               # exact f64 row, kernel-side
    on_select=lambda sel: print(len(sel), "points"),  # shift-drag box-select
)
```

**Fluent API** (imperative):

```python
import numpy as np
from fastcharts import Figure

n = 10_000_000
x = np.arange("2015-01-01", "2025-01-01", dtype="datetime64[s]")[:n]
y = np.cumsum(np.random.default_rng(0).normal(size=n))

Figure(title="10M points, interactive").line(x, y, name="random walk")
```

## What exists (Phase 0)

| Piece | Dossier § | Where |
|---|---|---|
| Native Rust core: zone maps, offset-f32 encode, M4 decimation | §22, §4/§16, §5 | `src/` |
| Zero-copy NumPy↔Rust via C ABI + ctypes (no registry deps at all) | §32, §33 | `python/fastcharts/_native.py` |
| Pure-NumPy fallback — the *defined*, loud no-wheel behavior | §33 | `python/fastcharts/_fallback.py` |
| Data-less `{traces, layout}` spec + column handles | §9 | `python/fastcharts/figure.py` |
| Single-copy column store, zone-map autorange, ingest copy accounting | §4, §22, §29 | `python/fastcharts/column.py` |
| Reflex-style composition API (`scatter_chart`/`line_chart` + marks/axes) | — | `python/fastcharts/components.py` |
| Full scatter: color (constant/colormap/palette), size, GPU-pick hover, Tier-2 density | §5, §28, §36c | `figure.py`, `channels.py`, `js/` |
| Box-select (shift-drag) → range filter, dim-unselected, `on_hover`/`on_select` | §34 | `figure.select_range`, `widget.py`, `js/` |
| anywidget client: WebGL2 instanced marks, SDF AA, binary buffers | §7, §33 | `js/src/fastcharts.js` |
| Pan/zoom = uniform update; kernel re-decimation round-trip on zoom, stale-while-revalidate | §17, §28 | widget + client |
| Viewport-recentered offsets → sub-ms precision inside 10-year series | §16 | tested in `tests/` |
| NaN never reaches vertex buffers | §19 | `figure.build_payload` |
| Memory report: every byte class itemized | §27 | `Figure.memory_report()` |
| Benchmark harness, run in CI every phase | §12 | `scripts/bench.py` |
| CI wheel matrix + install-size budget | §33 | `.github/workflows/ci.yml` |

### Architecture (Python-only, §32)

```
Python process                          Browser
┌──────────────────────────────┐        ┌──────────────────────────────┐
│ Figure / ColumnStore (NumPy   │  spec  │ anywidget ESM client          │
│ f64 canonical — the truth)    │ (JSON) │  WebGL2: instanced points,    │
│         │                     │ ─────► │  instanced line segments,     │
│ Rust core (C-ABI cdylib)      │ columns│  SDF antialiasing             │
│  zone maps · offset-f32 ·     │ (raw   │  pan/zoom = uniform update    │
│  M4 decimation                │  f32)  │  DOM chrome: axes/legend/title│
│         ▲                     │ ─────► │        │                      │
│         └── re-decimate view ◄─────────┘  debounced view change        │
└──────────────────────────────┘  msg + binary buffers (never base64)   │
```

- **Wire format = memory format**: relative-f32 columns move as raw widget
  buffers; the client wraps them in `Float32Array` views and uploads once. No
  JSON numbers anywhere (§29).
- **Offset encoding** (§4): canonical f64 stays kernel-side; the GPU sees
  `(v − offset) × scale` f32. Zoom re-decimation re-centers the offset on the
  viewport (§16), so ms-timestamps keep sub-ms precision at any zoom.
- **Tier 0/1** ship in Phase 0: direct instanced draw, and M4 (first/min/max/
  last per pixel column — pixel-accurate for lines) with kernel-side
  re-decimation of only the visible window on zoom. Tiers 2/3 (density pyramid,
  out-of-core) are Phases 2/4.

## Scatter — a full chart type (§5, §28, §36c)

```python
# constant, continuous colormap, or categorical palette — auto-detected
fig.scatter(x, y, color=values, colormap="viridis")   # continuous → LUT
fig.scatter(x, y, color=labels)                        # strings → palette
fig.scatter(x, y, size=weights, size_range=(3, 20))    # per-point size

# 30M points: auto-switches to a Tier-2 density surface (kernel-binned count
# grid, colormapped on the GPU, re-binned on zoom). Screen-bounded VRAM.
fig.scatter(bigx, bigy)          # density kicks in above ~200k points
fig.scatter(bigx, bigy, density=True)   # or force it
```

- **Color**: a CSS string (constant), a numeric array (continuous → colormap
  LUT), or a categorical array (factorized → CVD-safe palette). Ships as **one
  f32 per point + a LUT** — never per-point RGBA — so a colored, sized scatter
  is ~16 B/pt on the wire (§2 "typical ≤ 24 B/pt").
- **Hover**: GPU picking (an ID texture + 1-pixel readback, O(1) regardless of
  point count) resolves which point; the exact row is read from the **f64
  canonical store** kernel-side (§16) and shown in a DOM tooltip. Standalone
  HTML decodes the resident f32 for an approximate readout with no kernel.
- **Tier-2 density** (§5): above the density threshold the kernel bins the
  viewport into a count grid (`bin_2d`), ships it as one f32 buffer, and the
  client uploads it as an R32F texture and log-colormaps it — normalization
  domain recomputed per view so brightness is stable on zoom (§F6). Pan/zoom
  triggers a kernel re-bin of the visible window; the stale grid stays drawn
  until it arrives (§17). Dropping per-point color under aggregation is
  reported (`channels_dropped`), never silent (§28).
- **Select** (§34): shift-drag a box; the kernel resolves the range predicate to
  row indices, unselected marks dim on the GPU, and `on_select` fires with a
  `Selection` (indices + `.xy()` arrays, never JSON). `on_hover` fires with the
  exact f64 row. Double-click clears. Standalone HTML computes selection from the
  resident f32 with no kernel.

## Development

Requires Rust (stable), Python ≥ 3.9 with [uv](https://docs.astral.sh/uv/), Node ≥ 18 (build script only — no npm packages).

```bash
cargo test                       # Rust kernel tests
cargo build --release            # native core cdylib
node js/build.mjs                # bundle JS client into python/fastcharts/static/
uv venv && uv pip install -e ".[dev]"
uv run pytest                    # Python tests (native + fallback parity)
uv run ruff check . && uv run ruff format --check .
uv run ty check                  # typecheck
uv run python scripts/bench.py  # §12 harness
```

The JS client is a single dependency-free ES module — `js/build.mjs` just copies
it (anywidget) and wraps it (standalone IIFE for `to_html`). No bundler, no CDN,
no supply chain (§33: assets ship inside the wheel).

## Honest numbers (§2: every claim is mode-scoped)

- Direct scatter transport: **8 B/pt** on the wire (x,y as relative f32);
  canonical f64 kernel-side is 16 B/pt.
- Decimated lines: wire cost is **screen-bounded** (≤ 4 points per pixel
  column), independent of dataset size; zoom round-trips recompute only the
  visible window.

**vs Plotly & matplotlib** — measured, three-way ([`docs/benchmark.md`](docs/benchmark.md)).
At **10M points** (CI, Ubuntu):

| | fastcharts | matplotlib | Plotly WebGL | Plotly SVG |
|---|---|---|---|---|
| total time | **86 ms** | 3,230 ms | 33,907 ms | didn't finish |
| peak memory | **2 MB** | 553 MB | 1,584 MB | (113 s @ 3M) |
| payload | **768 KB** | 41 KB PNG | 49 KB PNG | 78 MB |

fastcharts is the only one **flat in N**: payload and memory stop growing once
density aggregation engages (§5). ~37× faster than matplotlib, ~394× than
Plotly-GL, 250–790× less memory. (fastcharts "total" is payload build; +~150 ms
for the actual browser render still leaves it ~14×/~140× ahead — see the report's
fairness note.) Run `scripts/bench_vs.py` (all three) or
`scripts/bench_scatter_native.py` (fastcharts arm, no deps).

Native-kernel throughput, measured (`scripts/bench_native.py`, single-threaded
scalar Rust — SIMD and worker threads are Phase 1; one dev machine, so treat as
order-of-magnitude, not a spec):

| points | encode f32 | zone maps | M4 (full) | zoom re-decimate | Tier-2 bin (512×384) |
|---|---|---|---|---|---|
| 1 M | 1410 Mpt/s | 400 Mpt/s | 253 Mpt/s | 0.05 ms | 166 Mpt/s (6 ms) |
| 10 M | 890 Mpt/s | 372 Mpt/s | 249 Mpt/s | 0.40 ms | 163 Mpt/s (61 ms) |

Two interactions that matter: re-decimating a line's visible window on zoom
(§28) is **0.40 ms for 10M points** (~250× under the §17 100–300 ms budget), and
binning 10M scatter points into a Tier-2 density grid is **61 ms** — a full
first paint, before any SIMD or the progressive-refinement coarse pass (§17).
`scripts/bench.py` adds the full figure→payload path once numpy installs; CI
publishes both per commit. No universal claims — see dossier §2/§31.

## Roadmap (dossier §11, amended §25/§35)

- **Phase 1**: worker-side compute, SharedArrayBuffer-where-available, gap
  semantics via segment lists, a11y semantic layer, Filter Tier A.
- **Phase 2**: Tier-2 density pyramid (WebGPU/WebGL2/CPU ladder), progressive
  refinement, fill-rate-aware tier heuristic, Filter Tier B.
- **Phase 3**: CPU reference rasterizer + perceptual-diff CI, native export.
- **Phase 4**: out-of-core tiling, shared-context dashboards, Filter Tier C
  (Falcon-style cross-filter index).
- **Phase 5**: Plotly-compat shim + generated conformance suite (§24/§30).
