# charts-exp / fastcharts

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
  `ABI_VERSION` in `src/lib.rs` *and* `python/fastcharts/_native.py` together
  on any signature change.
- `python/fastcharts/` — package. `_native.py` (ctypes) and `_fallback.py`
  (NumPy) must stay semantically identical; parity is tested. `components.py`
  is the Reflex-flavored composition API (`scatter_chart`/`line_chart` + marks/
  axes) — it builds a `Figure`; keep it dependency-free (no `reflex` import).
  `channels.py` resolves scatter color/size encodings.
- `js/src/*.js` — the render client as ordered parts (concat order in
  `js/build.mjs`; exports live only in `60_entries.js`), one dependency-free ES
  module. **No npm packages.** `node js/build.mjs` copies it to
  `python/fastcharts/static/` (committed artifacts).
- `tests/`, `scripts/bench.py` (§12 harness), `scripts/smoke_render.py`
  (headless Chromium pixel probe).

## Commands

```bash
cargo test && cargo build --release   # core
node js/build.mjs                     # regenerate static/ after JS edits
python3 scripts/abi_smoke.py          # C-ABI seam, stdlib only (no PyPI needed)
python3 scripts/render_smoke_nonumpy.py  # WebGL2 render path in headless Chromium
uv venv && uv pip install -e ".[dev]"
uv run pytest                         # + FASTCHARTS_FORCE_FALLBACK=1 pytest
uv run ruff check . && uv run ruff format . && uv run ty check
uv run python scripts/bench.py        # §12 benchmark harness
python3 scripts/bench_scatter_native.py --render   # fastcharts scatter, no deps
uv run python scripts/bench_vs.py     # three-way vs plotly/matplotlib (needs both)
```

The two `*_smoke*` scripts need neither numpy nor PyPI — they verify the
Python↔Rust ABI and the render client directly, and run first in CI.

## Invariants (from the dossier — don't regress silently)

- No JSON numbers on the wire; data moves as raw f32 buffers (§29).
- Canonical data is CPU-side f64; every GPU/derived buffer is a rebuildable
  cache (§27). NaN never reaches vertex buffers (§19).
- f32 uploads are offset-encoded; tick/hover math stays f64 (§4/§16).
- Every decimation/tier decision is recorded in the spec, never silent (§28).
- Claims are mode-scoped and benchmarked (§2); update README numbers from
  `scripts/bench.py`, don't invent them.
