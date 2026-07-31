# xy / xy

A high-performance charting engine. The authoritative design is
`spec/design-dossier.md` — **read the relevant § before changing behavior**;
code comments cite dossier sections (e.g. §16 = deep-zoom re-centering).

The entire `spec/` directory is the source of truth for intended behavior,
architecture, compatibility, benchmarks, release readiness, and contributor
contracts. Keep it current with every relevant code, configuration, build, and
release change. A change is incomplete while its affected specification is
missing, stale, or inconsistent with the implementation; resolve discrepancies
instead of treating the implementation alone as authoritative.

## Product North Star

XY is being built to outperform every competing charting library and become
the best overall charting system for Python. That goal spans every chart type
and every data scale, from a handful of values to billions of rows, across the
two dimensions users should not have to trade off: performance and
customization.

Treat every competitor lead as a concrete product gap. Work that affects a
user-visible capability should:

- compare XY with the relevant leaders, including Matplotlib, Seaborn, Plotly,
  Bokeh, Altair, Datashader, HoloViews/hvPlot, and emerging alternatives;
- add or extend reproducible evidence across small, medium, large, and massive
  data, covering startup, build and render time, interaction, memory, payload
  and export size, and multi-chart applications where applicable;
- update the capability matrix and visual examples when the improvement is
  about chart breadth or customization rather than timing; and
- commit the environment, raw results, output contracts, and reproduction
  commands needed to inspect the win and catch regressions.

The goal is not to win one large-scatter benchmark. XY should become the
library users choose for ordinary charts, massive data, every chart family,
notebooks, applications, static output, performance, and complete design
control.

## Layout

- `src/` — Rust core, **minimal external crates** (C ABI; one cdylib per
  platform serves every CPython version). Dependencies are allowed when they
  pay for themselves (measured win, small tree, well-maintained) — minimize,
  don't prohibit. Caveat: crates.io is unreachable from the dev sandbox, so a
  required crate must be vendored (`cargo vendor`) or the sandbox loses the
  ability to build/test the core; prefer feature-gated optional deps. Bump
  `ABI_VERSION` in `src/lib.rs` *and* `python/xy/_native.py` together
  on any signature change.
- `python/xy/` — package. `_native.py` (ctypes) binds the required
  Rust core; there is no NumPy fallback — `kernels.py` raises a clear
  ImportError if the native core can't load. `components.py`
  is the Reflex-flavored composition API (`scatter_chart`/`line_chart` + marks/
  axes) — the **only public chart-building surface**; keep it dependency-free
  (no `reflex` import). `_figure.py` is the internal scene/engine object
  (`Figure`) that composed charts compile to via `Chart.figure()`; it is not
  exported from `xy` (only `Selection` is public from it).
  `marks.py` is the declarative mark core: the single implementation of every
  chart kind, bound onto the internal `Figure` (one body, one signature, one
  set of defaults — parity is identity, not convention).
  `channels.py` resolves scatter color/size encodings. `channel.py` (singular)
  is the transport-agnostic message dispatcher (widget comm today, Reflex
  routes later) — it must never import the widget stack.
- `python/xy/pyplot/` — the matplotlib shim, fully contained
  (one-way dependency onto the public composition API; guardrails in
  `tests/pyplot/test_boundaries.py`). Corpus-defined compatibility:
  `tests/pyplot/corpus/` + `spec/matplotlib/compat.md`.
- `python/reflex_xy/` — the bundled Reflex integration (import namespace
  `reflex_xy`; design: `spec/design/reflex-integration.md`). Chart
  data rides the app's own websocket as a second socket.io namespace;
  figures live in a per-process registry rebuilt from Reflex state on miss.
  The source ships in every `xy` artifact; the `xy[reflex]` extra selects the
  supported Reflex floor while plain `xy` keeps no Reflex runtime dependency.
  The core `python/xy` package must never import Reflex. The render client is
  linked out of that package at app compile (no second copy to drift).
  Tests: `tests/reflex_adapter/` (skip unless Reflex is installed).
- `js/src/*.ts` — the render client as TypeScript ES modules (one module per
  former concat part; `60_entries.ts` is the entry and the only public export
  surface). `node js/build.mjs` typechecks (`js/tsconfig.json`), lints the
  shaders, and has vite bundle + minify into `python/xy/static/index.js`
  (anywidget ESM) and `standalone.js` (IIFE, `window.xy`). Those bundles are a
  **generated artifact, git-ignored, not committed** (§33): `hatch_build.py`
  builds them and force-includes them into the wheel/sdist at packaging time
  (exactly as it does the Rust core), so published distributions carry them
  prebuilt. From a source checkout run `npm ci && node js/build.mjs` once so the
  widget, HTML export, and tests have the bundles on disk. npm devDependencies
  (vite/typescript/playwright, pinned in `package-lock.json`) are build/test-time
  only — the shipped client stays runtime-dependency-free.
- `tests/`, `scripts/bench.py` (§12 harness), `scripts/smoke_render.py`
  (headless Chromium pixel probe).

## Commands

```bash
cargo test && cargo build --release   # core
npm ci                                # once per checkout: vite + tsc toolchain
node js/build.mjs                     # typecheck + regenerate minified static/ after JS edits
python3 scripts/abi_smoke.py          # C-ABI seam, stdlib only (no PyPI needed)
python3 scripts/render_smoke_nonumpy.py  # WebGL2 render path in headless Chromium
python3 scripts/append_stream_smoke.py   # streaming-append tail uploads + coalesced refines
uv sync --extra reflex --group dev
uv run pytest                         # native core required (no fallback)
python3 scripts/reflex_ws_smoke.py    # browser E2E vs the running Reflex demo app
uv run ruff check . && uv run ruff format . && uv run ty check
uv run python scripts/bench.py        # §12 benchmark harness
python3 scripts/bench_scatter_native.py --render   # xy scatter, no deps
uv run python scripts/bench_vs.py     # three-way vs plotly/matplotlib (needs both)
```

Before every commit or push, run the repository hooks and Ruff checks across the
full worktree. Do not commit if any of these commands fails:

```bash
uv run --with pre-commit pre-commit run --all-files
uv run ruff check .
uv run ruff format --check .
```

`abi_smoke`, `render_smoke_nonumpy`, and `append_stream_smoke` need neither
numpy nor PyPI — they verify the Python↔Rust ABI and the render client
directly, and run first in CI.

Never credit Claude in git history: no Claude author or committer identity,
no `Co-Authored-By: Claude` trailers, no AI attribution in commit messages,
PRs, or code. Set `git config user.name/user.email` to the human author
(e.g. from `git log origin/main`) before committing.

## Invariants (from the dossier — don't regress silently)

- No JSON numbers on the wire; data moves as raw f32 buffers (§29).
- Canonical data is CPU-side f64; every GPU/derived buffer is a rebuildable
  cache (§27). NaN never reaches vertex buffers (§19).
- f32 uploads are offset-encoded; tick/hover math stays f64 (§4/§16).
- Every decimation/tier decision is recorded in the spec, never silent (§28).
