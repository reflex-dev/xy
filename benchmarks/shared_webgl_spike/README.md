# Shared WebGL host experiment

This is a dependency-free architecture spike for
[`reflex-dev/xy#407`](https://github.com/reflex-dev/xy/issues/407). It isolates the
browser-level question behind Phase 3 of that proposal: can one WebGL2 context keep 50
independent DOM chart surfaces live without importing `virtual-webgl` or another renderer?

This directory does **not** integrate the host with xy's production `ChartView`. It uses a
small synthetic line renderer so context sharing, state boundaries, presentation copies,
picking, and recovery can be measured independently before the production refactor.

It implements two rendering backends over the same chart model and shaders:

- **Shared GLHost:** one detached WebGL2 canvas/context renders every chart, then
  synchronously presents each completed frame into that chart's visible 2D canvas with
  `drawImage`.
- **Native contexts:** each visible chart canvas owns a separate WebGL2 context, exposing
  the browser's live-context ceiling.

The page exercises:

- 50 continuously streaming, independently colored line charts;
- one VBO/VAO and one lazy pick framebuffer per chart;
- explicit WebGL state reset at every shared-client boundary;
- deliberately poisoned state between charts;
- asymmetric pixel canaries for blank, stale, flipped, cropped, or cross-chart frames;
- three exact encoded-ID checks on every live chart (150 checks at the default count);
- a forced 17-pixel host crop offset, so verification covers a grown backing canvas;
- GPU hit-buffer picking (the interactive path returns the last covered sample, not the
  mathematically nearest sample);
- grow-only host backing dimensions and responsive chart resizing;
- shared and per-chart `WEBGL_lose_context` recovery;
- JavaScript-side batch, upload, draw, and 2D presentation submission timing.

## Run

From the repository root:

```sh
python3 -m http.server 4173 --directory benchmarks/shared_webgl_spike
```

Then open <http://localhost:4173/>.

The renderer and chart count are encoded in the query string so A/B changes reload the
document and cannot accidentally retain contexts from the previous variant:

```text
?mode=shared&count=50
?mode=native&count=50
```

## Automation surface

Once `window.__EXPERIMENT_READY === true`:

```js
await window.__sharedWebglExperiment.verify();
await window.__sharedWebglExperiment.benchmark(3000);
await window.__sharedWebglExperiment.cycleContext();
window.__sharedWebglExperiment.snapshot();
```

Results are also exposed as `window.__LAST_CHECK` and `window.__LAST_BENCHMARK`.
The capture utility writes one raw JSON file per attempted profile run plus
`summary-input.json` to a caller-selected directory. These generated files are local evidence,
not tracked repository reports. Keep them under the ignored local `results/` directory or attach
them as ephemeral CI/PR artifacts when they are needed for review.

### Governed local capture

Use the versions prescribed by the repository [benchmark runbook](../README.md), start the
static server with Python 3.12, and run the capture utility under Node 22. It enforces at least
three repetitions and launches a fresh Chromium process for every shared or native profile run:

```bash
# Terminal 1:
python3.12 -m http.server 4173 --directory benchmarks/shared_webgl_spike

# Terminal 2, from the repository root:
CAPTURE_DIRECTORY="benchmarks/shared_webgl_spike/results/capture-$(date -u +%Y%m%dT%H%M%SZ)"
PLAYWRIGHT_CHROMIUM="$(npx --yes node@22 -e \
  'console.log(require("playwright").chromium.executablePath())')"
npx --yes node@22 benchmarks/shared_webgl_spike/capture.mjs \
  --chromium "$PLAYWRIGHT_CHROMIUM" \
  --repetitions 3 \
  --duration-ms 3000 \
  --output-dir "$CAPTURE_DIRECTORY/raw"
```

Every profile/repetition is written immediately as raw JSON, including failed attempts, before
it can enter the successful-run aggregate. Shared-first and native-first ordering alternates by
repetition. The same directory receives `summary-input.json`, whose numeric benchmark fields are
medians of the successful cold-process runs; integer counts select the lower observed middle
value when an even number of attempts succeeds. Rate and interval fields are re-derived from
those medians, and stable-context presentation totals are derived from productive batches times
live charts, so `summary-input.json` remains internally consistent.

The runner self-checks the capture before returning success. Every requested run must complete;
structural workload fields must agree; productive batch counts must be positive; presentation
counts must be conserved; per-live-chart correctness coverage and recovery invariants must hold;
and unexpected page diagnostics fail their attempt. Aggregation failures are recorded in
`summary-input.json` and make the command exit nonzero. The raw attempts and `summary-input.json`
are the complete output contract—do not translate them into a separate report or pass them to the
generic benchmark-report validator.

Keep `$CAPTURE_DIRECTORY/raw` local or upload it as an ephemeral review artifact. Do not add it
to the repository.

The utility rejects a dirty worktree and fingerprints the served `index.html`, `experiment.js`,
and `styles.css` against the local checkout before associating results with the Git revision. It
records Python, Node, Playwright, browser, and platform details without retaining an absolute
browser executable path. Browser evaluation calls have Node-side deadlines. Page errors and all
warning/error console messages are preserved in raw JSON. They fail the attempt except for two
source-, phase-, and count-capped Chromium diagnostics: native context eviction while the 50
contexts initialize, and the shared verifier's intentional Canvas 2D readback. Commit the capture
utility and harness first, then run them from that clean revision; the runner records the revision
in every raw attempt and in `summary-input.json`.

Timing around `drawImage` measures JavaScript submission cost, not completed GPU work.
Native mode can look faster after browser eviction because it is rendering fewer live charts;
compare `fullyLive` and `chartPresentationsPerSecond`, not frame time alone.

The default benchmark profile leaves **State stress** off to approximate production. The
correctness check always enables state poisoning regardless of that toggle. Enable the toggle
to benchmark the torture profile.

## Scope of the experiment

The spike tests the proposed blit architecture with synthetic chart surfaces and one shared
WebGL2 context. A successful local run does not establish production xy performance or satisfy
issue #407's acceptance criteria by itself. Integration still requires `ChartView` to accept a
host-owned context and render target, invalidate renderer caches at chart switches, coalesce
dirty clients, and preserve xy view state through a host-wide context rebuild.

The experiment intentionally leaves the dossier's §18 shared-context option marked
unimplemented. A later production phase must update the specification when the runtime behavior
actually ships.

## Deliberate limits

- The renderer is synthetic: there is no `ChartView`, LOD, kernel, export, selection, or shared
  column-cache integration.
- The spike implements only per-chart `drawImage` blits, not the single full-page-canvas mode.
- State reset covers the WebGL state touched by this renderer; xy integration must audit every
  production state dependency and cache.
- Exact-ID checks isolate one requested vertex. Interactive dense hit testing retains
  last-covered-sample semantics rather than a nearest-point oracle.
- Context recovery rebuilds the synthetic GPU resources; it does not exercise xy pan/zoom state.
- The capture utility reports medians of local cold-browser-process runs and measures JavaScript
  submission cost, not completed GPU work or an xy speedup claim.
