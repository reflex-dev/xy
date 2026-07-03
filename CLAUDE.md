# charts-exp / fastcharts

A high-performance charting engine. The authoritative design is
`docs/design-dossier.md` — **read the relevant § before changing behavior**;
code comments cite dossier sections (e.g. §16 = deep-zoom re-centering).

## Layout

- `src/` — Rust core, **zero external crates by design** (C ABI, no registry
  access needed; one cdylib per platform serves every CPython version). Bump
  `ABI_VERSION` in `src/lib.rs` *and* `python/fastcharts/_native.py` together
  on any signature change.
- `python/fastcharts/` — package. `_native.py` (ctypes) and `_fallback.py`
  (NumPy) must stay semantically identical; parity is tested.
- `js/src/fastcharts.js` — the entire render client, one dependency-free ES
  module. **No npm packages.** `node js/build.mjs` copies it to
  `python/fastcharts/static/` (committed artifacts).
- `tests/`, `scripts/bench.py` (§12 harness), `scripts/smoke_render.py`
  (headless Chromium pixel probe).

## Commands

```bash
cargo test && cargo build --release   # core
node js/build.mjs                     # regenerate static/ after JS edits
uv venv && uv pip install -e ".[dev]"
uv run pytest                         # + FASTCHARTS_FORCE_FALLBACK=1 pytest
uv run ruff check . && uv run ruff format . && uv run ty check
```

## Invariants (from the dossier — don't regress silently)

- No JSON numbers on the wire; data moves as raw f32 buffers (§29).
- Canonical data is CPU-side f64; every GPU/derived buffer is a rebuildable
  cache (§27). NaN never reaches vertex buffers (§19).
- f32 uploads are offset-encoded; tick/hover math stays f64 (§4/§16).
- Every decimation/tier decision is recorded in the spec, never silent (§28).
- Claims are mode-scoped and benchmarked (§2); update README numbers from
  `scripts/bench.py`, don't invent them.
