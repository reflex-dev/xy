# xy / xy

A high-performance charting engine. The authoritative design is
`docs/design-dossier.md` — **read the relevant § before changing behavior**;
code comments cite dossier sections (e.g. §16 = deep-zoom re-centering).

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
  `tests/pyplot/corpus/` + `docs/matplotlib-compat.md`.
- `js/src/*.js` — the render client as ordered parts (concat order in
  `js/build.mjs`; exports live only in `60_entries.js`), one dependency-free ES
  module. **No npm packages.** `node js/build.mjs` copies it to
  `python/xy/static/` (committed artifacts).
- `tests/`, `scripts/bench.py` (§12 harness), `scripts/smoke_render.py`
  (headless Chromium pixel probe).

## Commands

```bash
cargo test && cargo build --release   # core
node js/build.mjs                     # regenerate static/ after JS edits
python3 scripts/abi_smoke.py          # C-ABI seam, stdlib only (no PyPI needed)
python3 scripts/render_smoke_nonumpy.py  # WebGL2 render path in headless Chromium
uv venv && uv pip install -e ".[dev]"
uv run pytest                         # native core required (no fallback)
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

The two `*_smoke*` scripts need neither numpy nor PyPI — they verify the
Python↔Rust ABI and the render client directly, and run first in CI.

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
- Claims are mode-scoped and benchmarked (§2); update README numbers from
  `scripts/bench.py`, don't invent them.
