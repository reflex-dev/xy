# fastcharts

A faster charting engine, per the design dossier in
[`docs/design-dossier.md`](docs/design-dossier.md): **cost scales with pixels on
screen, not points in the dataset.** Plotly's ceilings are removed by four
changes — GPU rendering (not one SVG node per point), binary columnar transport
(not JSON), a native Rust core in the Python process (not main-thread compute),
and a multi-tier level-of-detail system that never ships or draws more
primitives than the screen can show.

**Status: Phase 0** (of the dossier's §11/§25/§35 milestones) — prove the
memory/scale thesis end to end.

```python
import numpy as np
from fastcharts import Figure

n = 10_000_000
x = np.arange("2015-01-01", "2025-01-01", dtype="datetime64[s]")[:n]
y = np.cumsum(np.random.default_rng(0).normal(size=n))

fig = Figure(title="10M points, interactive")
fig.line(x, y, name="random walk")
fig            # renders in Jupyter / VS Code / Colab / Marimo via anywidget
fig.to_html("chart.html")   # or standalone interactive HTML
```

## What exists (Phase 0)

| Piece | Dossier § | Where |
|---|---|---|
| Native Rust core: zone maps, offset-f32 encode, M4 decimation | §22, §4/§16, §5 | `src/` |
| Zero-copy NumPy↔Rust via C ABI + ctypes (no registry deps at all) | §32, §33 | `python/fastcharts/_native.py` |
| Pure-NumPy fallback — the *defined*, loud no-wheel behavior | §33 | `python/fastcharts/_fallback.py` |
| Data-less `{traces, layout}` spec + column handles | §9 | `python/fastcharts/figure.py` |
| Single-copy column store, zone-map autorange, ingest copy accounting | §4, §22, §29 | `python/fastcharts/column.py` |
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
- Run `scripts/bench.py` for throughput on your machine; CI publishes the
  numbers per commit. No universal claims — see dossier §2/§31.

## Roadmap (dossier §11, amended §25/§35)

- **Phase 1**: worker-side compute, SharedArrayBuffer-where-available, gap
  semantics via segment lists, a11y semantic layer, Filter Tier A.
- **Phase 2**: Tier-2 density pyramid (WebGPU/WebGL2/CPU ladder), progressive
  refinement, fill-rate-aware tier heuristic, Filter Tier B.
- **Phase 3**: CPU reference rasterizer + perceptual-diff CI, native export.
- **Phase 4**: out-of-core tiling, shared-context dashboards, Filter Tier C
  (Falcon-style cross-filter index).
- **Phase 5**: Plotly-compat shim + generated conformance suite (§24/§30).
