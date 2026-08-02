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
The captured run used for this spike is preserved as both a
[readable report](./RESULTS.md) and a
[machine-readable result summary](./results/chromium-2026-08-02.json).

### Harness-to-report mapping

The browser API returns camelCase JavaScript objects; the committed
`shared-webgl-spike` report is a manually assembled, snake_case summary. Preserve the raw
`verify()`, `benchmark()`, `cycleContext()`, and `snapshot()` results for both modes, then apply
these mappings:

| Harness field | Report field |
| --- | --- |
| `requestedCharts`, `liveCharts`, `liveContexts`, `fullyLive` | `profiles.<mode>.requested_charts`, `live_charts`, `live_contexts`, `fully_live` |
| `snapshot().stats.createdContexts` (native) | `profiles.native.created_contexts` |
| `verify().pass`, `canaryChecks`, `canaryFailures`, `pickChecks`, `pickFailures` | `correctness.pass`, `canary_checks`, `canary_failures`, `pick_checks`, `pick_failures` |
| `verify().stateStress`, `cropOffsetPixels`, `timestamp` | `correctness.state_stress`, `crop_offset_pixels`, `verified_at_utc` |
| `requestedDurationMs`, `durationMs`, `targetFps`, `observedFps` | `benchmark.requested_duration_ms`, `benchmark.duration_ms`, `benchmark.target_fps`, `benchmark.observed_fps` |
| `productiveBatches`, `expectedBatches`, `droppedIntervals` | `benchmark.productive_batches`, `expected_batches`, `dropped_intervals` |
| `chartPresentations`, `chartPresentationsPerSecond` | `benchmark.chart_presentations`, `chart_presentations_per_second` |
| `frameMs`, `presentMsPerChart`, `stateStress` | `benchmark.frame_ms`, `present_ms_per_chart`, `state_stress` |
| `pointsPerChart`, `contextLossesDuringRun`, `contextRestoresDuringRun` | `benchmark.points_per_chart`, `context_losses_during_run`, `context_restores_during_run` |
| `viewportCssPixels`, `dpr` | `environment.viewport_css_pixels`, `device_pixel_ratio` |
| `benchmark().environment.webgl.vendor`, `renderer`, `version`, `shadingLanguageVersion` | `environment.webgl.vendor`, `renderer`, `version`, `shading_language_version` |
| Post-cycle `snapshot().contextLosses` minus pre-cycle `snapshot().contextLosses` | `recovery.context_losses` |
| Post-cycle `snapshot().contextRestores` minus pre-cycle `snapshot().contextRestores` | `recovery.context_restores` |
| Post-cycle `snapshot().lastCheck.expectedCharts`, `lastCheck.pass`, and `stats.liveCharts` | `recovery.expected_charts`, `recovery.correctness_after_restore`, `recovery.live_charts_after_restore` |

`requestedDurationMs` is the configured duration passed to `benchmark()`; `durationMs` is the
observed elapsed time. Keep both values distinct in the report.

`canvasPixels` is a range, while `environment.canvas_pixels` records one exact common chart
size. Set `canvas_pixels.width` only when `minWidth === maxWidth`, and set
`canvas_pixels.height` only when `minHeight === maxHeight`. If either range does not collapse,
do not silently choose one endpoint: rerun with uniform chart sizes or extend the report schema
to preserve the range.

Run the cycle and record recovery for both profiles. Take one `snapshot()` immediately before
`cycleContext()` and another after it completes. `contextLosses` and `contextRestores` are
cumulative lifetime counters, so report each recovery value as the post-cycle counter minus its
pre-cycle counterpart; do not copy the post-cycle total directly. The post-cycle snapshot's
`lastCheck` is the recovery verification: map its `expectedCharts` and `pass` values alongside
`stats.liveCharts` as shown above. If a profile cannot attempt or complete restoration,
represent that limitation explicitly in the report and results narrative rather than omitting
its recovery outcome. Set `visible_frames_during_loss_checked` to `true` only when a separate
canary actually inspected the visible canvases during the loss window.

### Governed reference-hardware capture

Use the versions prescribed by the repository [benchmark runbook](../README.md), start the
static server with Python 3.12, and run the capture utility under Node 22. It enforces at least
three repetitions and launches a fresh Chromium process for every shared or native profile run:

```bash
# Terminal 1:
python3.12 -m http.server 4173 --directory benchmarks/shared_webgl_spike

# Terminal 2, from the repository root:
PLAYWRIGHT_CHROMIUM="$(npx --yes node@22 -e \
  'console.log(require("playwright").chromium.executablePath())')"
npx --yes node@22 benchmarks/shared_webgl_spike/capture.mjs \
  --chromium "$PLAYWRIGHT_CHROMIUM" \
  --repetitions 3 \
  --duration-ms 3000 \
  --output-dir benchmarks/shared_webgl_spike/results/raw/chromium-YYYY-MM-DD
```

Every profile/repetition is written immediately as raw JSON, including failed attempts. The
same directory receives `summary-input.json`, whose numeric benchmark fields are medians of the
successful cold-process runs; rate and interval fields are re-derived from those medians so the
published report remains internally consistent. Commit the capture utility and schema first,
then run it from that clean revision and record that revision in the final report.

Timing around `drawImage` measures JavaScript submission cost, not completed GPU work.
Native mode can look faster after browser eviction because it is rendering fewer live charts;
compare `fullyLive` and `chartPresentationsPerSecond`, not frame time alone.

The default benchmark profile leaves **State stress** off to approximate production. The
correctness check always enables state poisoning regardless of that toggle. Enable the toggle
to benchmark the torture profile.

## Scope of the result

The spike demonstrates that the proposed blit architecture can keep 50 synthetic chart
surfaces live while owning one WebGL2 context. It does not establish production xy performance
or satisfy issue #407's acceptance criteria by itself. Integration still requires `ChartView`
to accept a host-owned context and render target, invalidate renderer caches at chart switches,
coalesce dirty clients, and preserve xy view state through a host-wide context rebuild.

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
- Timings are one local run of JavaScript submission cost, not completed GPU work or an xy
  speedup claim.
