# Security Audit - 2026-07-06

Scope: XY Python package, standalone/browser client, Rust native core,
HTML/PNG export paths, example app dependency manifests, CI/release workflows,
and packaging verifiers.

This was a source audit plus local tooling run, not a third-party penetration
test. Browser-engine compromise, GPU driver bugs, and production deployments of
the Reflex demo are out of scope except where the library can reduce exposure.

## Fixed Findings

### XY-SEC-2026-01: Standalone HTML lacked a defensive CSP

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

#### Status as of 2026-07-20 (XY-SEC-2026-01)

`worker-src` is no longer `'none'`. It was relaxed to `worker-src blob:` on
2026-07-08 in commit b353dea ("Standalone density re-bin in a Web Worker"), so
the standalone density re-bin worker can boot from a Blob URL of its own
bundled source. No external worker script can load under that directive. The
shipped policy is `_STANDALONE_CSP` in `python/xy/export.py`; every other
directive listed above is unchanged. `tests/test_static_client_security.py`
asserts the directive is exactly `worker-src blob:`, and
`docs/guides/serving-csp-and-offline-use.md` documents it for host operators.

### XY-SEC-2026-02: Legend swatches accepted raw CSS paint strings

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

### XY-SEC-2026-03: PNG export disabled Chromium sandbox by default

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

#### Status as of 2026-07-20 (XY-SEC-2026-03)

The last bullet no longer holds as written. Commit 8cda831 ("Stabilize Chromium
PNG export in CI"), landed 2026-07-06, added an automatic fallback:
`html_to_png` launches sandboxed first, and if that attempt produces no
screenshot it rebuilds the argv with `--no-sandbox` inserted and re-runs before
raising. The error message on total failure reports both attempts.
`_browser_session` mirrors this for the persistent path, retrying
`ChromiumSession(..., sandbox=False)` on `ChromiumError`. So `--no-sandbox` can
appear without the caller requesting it.

Sandboxing remains the default and the first attempt; the escape hatch and the
threading through `Figure.to_png()` are unchanged. The fallback is an accepted
residual risk taken to keep CI and container rasterization working where the
sandbox cannot initialize. Follow-up pending: make the fallback opt-in (or at
minimum warn on the downgrade) so a silent sandbox loss is observable.

#### Resolution as of 2026-07-21 (XY-SEC-2026-03)

The automatic fallback has been removed from both public browser-export paths.
A sandboxed launch now fails once with an actionable diagnostic and never adds
`--no-sandbox`. Trusted repository CI that needs the downgrade passes
`sandbox=False` at the call site, making the exception reviewable. Unit tests
assert the exact launch count, sandbox arguments, and failure guidance for the
one-shot and persistent paths. This closes TST-NI-025.

### XY-SEC-2026-04: Pyramid native-boundary validation was weaker than other kernels

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

### XY-CI-2026-01: Clippy hard gate failed on staged SIMD helpers

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
- Release workflow builds native wheels with `XY_REQUIRE_CARGO=1`,
  verifies wheel contents, smokes native backend loading, and publishes through
  PyPI trusted publishing/OIDC.
- Wheel and sdist verifiers check required files, native/pure expectations,
  unsafe archive paths, duplicate members, generated junk, and metadata floors.
- CodSpeed and benchmark workflows assert native backend before performance
  runs.

#### Status as of 2026-07-20 (Confirmed Controls)

The Rust core is no longer std-only, so the "Cargo dependency tree is empty"
control above and the `cargo tree --locked` evidence line below are both
superseded. Commit c3c867b, landed 2026-07-11, added one direct dependency to
`Cargo.toml` — `png = "0.18.1"`, for the native raster encoder's fdeflate fast
path — which pulls in eight transitive crates: `bitflags`, `crc32fast`,
`cfg-if`, `fdeflate`, `simd-adler32`, `flate2`, `miniz_oxide`, and `adler2`.
`Cargo.lock` therefore holds nine third-party packages plus `xy-core`.

The tree is still shallow and single-rooted, but "no third-party Rust crates"
is no longer an accurate standing control. Follow-up pending: add `cargo audit`
(or `cargo deny`) to CI now that a third-party tree exists, matching the
`pip-audit` coverage already run on the Python side.

## Tooling Evidence

- `uv tool run pip-audit --progress-spinner off .`: no known vulnerabilities.
- `uv tool run pip-audit --progress-spinner off -r requirements.txt` from
  `examples/reflex/`: no known vulnerabilities; local editable
  `xy` is skipped because it is not a PyPI package.
- `cargo tree --locked`: only `xy-core`, no third-party Rust crates. (True on
  the audit date only; superseded by the 2026-07-20 status note above, which
  records `png` plus eight transitive crates.)
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
- `XY_NATIVE_LIB` intentionally allows loading a developer-specified
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

#### Status as of 2026-07-20 (Residual Risks)

The first two bullets above understate the current exposure. "Keep Chromium's
sandbox enabled" is caller-side advice that the library does not enforce end to
end, and unsandboxed launches are not confined to CI smoke scripts: since commit
8cda831 the public export path downgrades itself automatically. `html_to_png`
re-runs with `--no-sandbox` inserted when the sandboxed launch produces no
screenshot (`python/xy/export.py:509-526`, the retry itself at `:511-519` and
the two-attempt error assembly through `:526`), and `_browser_session` retries
`ChromiumSession(..., sandbox=False)` on `ChromiumError`
(`python/xy/export.py:926-931`). Neither path emits a warning, so the downgrade
is silent. See [the 2026-07-20 status note under
XY-SEC-2026-03](#status-as-of-2026-07-20-xy-sec-2026-03) above and
`spec/api/export.md` §7.

Read that way, `sandbox=True` is a preference, not a guarantee: rendering
untrusted HTML through `to_png()` can execute unsandboxed on a host where the
sandbox cannot initialize. Container/worker isolation is therefore the load-
bearing control, not the sandbox flag. Follow-up pending (same item as
XY-SEC-2026-03): make the fallback opt-in, or at minimum warn on the downgrade,
so a sandbox loss is observable.

The 2026-07-21 resolution under XY-SEC-2026-03 supersedes this residual-risk
status: `sandbox=True` is now enforced end to end and never downgrades itself.
