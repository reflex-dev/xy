# Browser Conformance Matrix Policy

This is the normative TST-NI-015 contract for the shared shipped-renderer
fixture. It is deliberately bounded rather than a Cartesian product: six
reviewed cases cover every required tier, representative mark family, DPR,
motion preference, and axis class, and every case runs unchanged in Chromium,
Firefox, and WebKit.

## Reviewed matrix

| Case | Tier / mark | DPR | Motion | Axis contract |
| --- | --- | ---: | --- | --- |
| `direct-linear-scatter-dpr1-reduced` | direct scatter | 1 | reduced | linear x/y; full keyboard/live-region anchor |
| `decimated-log-line-dpr2-motion` | decimated line | 2 | no preference | logarithmic x |
| `direct-category-bar-dpr1-motion` | direct bar | 1 | no preference | category x with exact category labels |
| `direct-linear-heatmap-dpr2-reduced` | direct heatmap | 2 | reduced | linear x/y |
| `direct-named-mesh-dpr1-motion` | direct triangle mesh | 1 | no preference | trace bound to named `x2` / `y2` axes |
| `density-linear-scatter-dpr2-reduced` | density scatter | 2 | reduced | linear x/y |

The catalog is exact. `scripts/browser_conformance.mjs --list-cases` exposes it,
and validation fails on a missing, extra, duplicate, or metadata-mismatched
case. This keeps the required coverage explicit while preventing accidental
growth into hundreds of redundant browser contexts.

## Required assertions

Every case must prove a nonzero root/canvas layout, accessible chart region and
plot image, named toolbar controls and one active toggle, expected summary and
axis-title text, the declared GPU kind/tier/axis binding, nonblank WebGL pixels,
the requested media preference, and a backing store matching DPR 1 or 2.
Reduced-motion cases must bypass animated view state; no-preference cases must
enter it. The scatter anchor additionally preserves the existing keyboard,
live-region, exact-reply, transition-suppression, Escape, and stale-reply
assertions.

The same case is compared to Chromium in each other selected engine. DOM layout
uses CSS pixels and may differ by at most 4 px. The 32 × 20 RGBA signature has a
mean absolute per-channel tolerance of 12 on the 0–255 scale. Lit-pixel count
must stay within 0.8–1.2 of Chromium, and every render must contain at least 80
lit WebGL pixels. These reviewed tolerances accommodate engine rasterization
without turning the gate into a blank-chart health check; changes require
review of this policy and retained evidence.

## Environment, evidence, and failure policy

The hard `browser_conformance` CI job uses Node 22, package-pinned Playwright
`1.61.1`, its bundled Chromium/Firefox/WebKit revisions, Ubuntu's Xvfb display,
a 760 × 480 CSS viewport, and a 1920 × 1200 virtual screen for DPR 2. It runs:

```bash
node scripts/browser_conformance.mjs --evidence browser-conformance-evidence.json
```

`make check-conformance` is the local entry point after all three Playwright
engines are installed. Default and CI execution require all three engines with
no skip path; an explicit `--browsers` subset is only a local diagnostic. A
missing selected engine, launch failure, missing WebGL2, page error, absent
matrix case, semantic failure, or comparison failure exits nonzero. CI retains
`browser-conformance-evidence.json` as the `browser-conformance-evidence`
artifact even on failure. The JSON records the exact matrix, environment,
browser versions, semantic/layout/DPR/motion observations, raster metrics,
thresholds, and signature digests.

Independent negative controls remove a required catalog case, corrupt a pixel
signature, and shift layout beyond tolerance. All three mutations must be
rejected before the real browser matrix can pass; `--self-test` exposes those
controls without launching a browser.
