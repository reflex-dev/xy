# Security Audit - 2026-07-06

Scope: FastCharts Python package, standalone/browser client, Rust native core,
HTML/PNG export paths, example app dependency manifests, CI/release workflows,
and packaging verifiers.

This was a source audit plus local tooling run, not a third-party penetration
test. Browser-engine compromise, GPU driver bugs, and production deployments of
the Reflex demo are out of scope except where the library can reduce exposure.

## Fixed Findings

### FC-SEC-2026-01: Standalone HTML lacked a defensive CSP

Severity: medium defense-in-depth.

`Figure.to_html()` already escaped inline JSON and bundled JavaScript correctly,
but the exported single-file document did not restrict network fetches or
external resources. A malicious CSS paint string or future client regression
could have caused unintended outbound loads when a user opened a chart file.

Fix:

- Added a standalone `Content-Security-Policy` meta tag with
  `default-src 'none'`, `connect-src 'none'`, `img-src data:`, `worker-src
  'none'`, `object-src 'none'`, `base-uri 'none'`, and `form-action 'none'`.
- Kept `script-src 'unsafe-inline'` and `style-src 'unsafe-inline'` because the
  file is intentionally portable and self-contained.
- Added regression coverage that the CSP is emitted before scripts.

Strict nonce/hash CSP still requires a host wrapper that serves the JS bundle as
a separate asset.

### FC-SEC-2026-02: Legend swatches accepted raw CSS paint strings

Severity: medium.

Trace colors are user-controlled. The WebGL mark path resolves colors through
`style.color`, but legend swatches assigned the raw value to
`style.background`. CSS backgrounds can include `url(...)`, creating a network
fetch surface in exported or embedded charts.

Fix:

- Hardened color parsing for non-string values and malformed hex colors.
- Added `safeCssPaint(...)`, which resolves user colors only through the CSS
  color parser and converts them to sanitized `rgba(...)`.
- Legend swatches now use sanitized paints; internal colormap gradients remain
  fixed library-generated strings.
- Added static client tests that guard the sanitized legend sink.

### FC-SEC-2026-03: PNG export disabled Chromium sandbox by default

Severity: medium.

`html_to_png()` accepts arbitrary HTML and launched Chromium with
`--no-sandbox`. Even though it used an argv list and no shell, disabling the
browser sandbox is the wrong default for user-facing rasterization.

Fix:

- Chromium sandboxing is now enabled by default.
- Added `sandbox=False` as an explicit escape hatch for trusted HTML in
  constrained CI/container environments.
- Threaded the option through `Figure.to_png()` and composed chart `to_png()`.
- Added tests proving `--no-sandbox` only appears when explicitly requested.

### FC-SEC-2026-04: Pyramid native-boundary validation was weaker than other kernels

Severity: low/medium robustness.

The newer tile-pyramid helpers accepted invalid bounds, bool-like dimensions,
oversized base dimensions, and bool handles more loosely than the older kernel
wrappers. Most failures returned a native sentinel instead of raising at the
Python boundary.

Fix:

- Added strict `base_dim`, handle, finite range, equal-length, and screen-size
  validation to both native and fallback pyramid wrappers.
- Rejected bool values before they can alias integer handles or dimensions.
- Added parity tests covering native-dispatch and fallback behavior.

### FC-CI-2026-01: Clippy hard gate failed on staged SIMD helpers

Severity: CI hardening.

The CI workflow runs `cargo clippy --all-targets -- -D warnings`, but the staged
SIMD module had intentionally unused helpers and failed that command.

Fix:

- Added a narrow file-level `allow(dead_code)` with rationale on `src/simd.rs`.
- Verified the exact CI clippy command now passes.

## Confirmed Controls

- Standalone JSON uses `json.dumps(..., allow_nan=False)` and escapes `<`, `>`,
  `&`, U+2028, and U+2029 before embedding in inline script.
- Bundled inline JavaScript escapes `</` so future literal `</script>` text
  cannot close the script element.
- Browser user-facing text surfaces use `textContent` or text nodes for titles,
  labels, legends, categories, and tooltips.
- The only `innerHTML` sink is fixed internal SVG modebar icons.
- The client has no `eval`, `new Function`, `document.write`,
  `insertAdjacentHTML`, or `outerHTML` use in source security checks.
- Rust FFI functions return sentinels on invalid pointer/argument combinations;
  Python wrappers validate public shape/range/dimension inputs before native
  calls.
- Cargo dependency tree is empty; the Rust core is std-only.
- The JS bundle build is dependency-free source concatenation.
- Release workflow builds native wheels with `FASTCHARTS_REQUIRE_CARGO=1`,
  verifies wheel contents, smokes native backend loading, and publishes through
  PyPI trusted publishing/OIDC.
- Wheel and sdist verifiers check required files, native/pure expectations,
  unsafe archive paths, duplicate members, generated junk, and metadata floors.
- CodSpeed and benchmark workflows assert native backend before performance
  runs.

## Tooling Evidence

- `uv tool run pip-audit --progress-spinner off .`: no known vulnerabilities.
- `uv tool run pip-audit --progress-spinner off -r requirements.txt` from
  `reflex_fastcharts_app/`: no known vulnerabilities; local editable
  `fastcharts` is skipped because it is not a PyPI package.
- `cargo tree --locked`: only `fastcharts-core`, no third-party Rust crates.
- `node js/build.mjs --check`: static JS bundles fresh.
- `make check-security`: passed.
- `make check-ci`: passed.
- `.venv/bin/ruff check .`: passed.
- `.venv/bin/ruff format --check .`: passed.
- `cargo test`: passed, 32 Rust tests.
- `cargo clippy --all-targets -- -D warnings`: passed after CI hardening.
- `.venv/bin/python scripts/check_python_floor.py`: passed.
- `.venv/bin/python -m pytest -q`: 619 passed, 4 skipped.
- `.venv/bin/python scripts/png_export_smoke.py`: skipped locally because no
  Chromium binary was available.
- `bandit -r ... --severity-level medium`: one low-confidence false positive in
  `scripts/render_smoke_nonumpy.py`, where a browser smoke-test HTML fixture is
  misidentified as SQL construction. No high-severity findings.

## Residual Risks And Follow-Ups

- Rendering untrusted HTML is still a browser attack surface. Keep Chromium's
  sandbox enabled, and isolate arbitrary-user export workloads in a dedicated
  container or worker account.
- CI/browser smoke scripts still pass `--no-sandbox` for trusted generated
  pages. That is separate from the public `to_png()` default, but it should not
  be copied into production services.
- `FASTCHARTS_NATIVE_LIB` intentionally allows loading a developer-specified
  native library. Treat that environment variable as trusted process
  configuration, not user input.
- The Reflex demo live-drilldown endpoint is local/demo infrastructure and is
  not authenticated or rate-limited as a production API. Add auth, quotas, and
  request-size policy before exposing an equivalent service publicly.
- Bun was not installed locally and the Reflex-generated frontend uses
  `bun.lock`, not an npm lockfile, so the JS dependency advisory audit for the
  demo app could not be run faithfully here. Run `bun audit` in an environment
  with Bun installed.
- This audit did not perform browser fuzzing, GPU-driver fuzzing, native memory
  sanitizer runs, or a hosted-app penetration test.
