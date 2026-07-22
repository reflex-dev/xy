# Reviewed Visual Baselines

Status: hard CI evidence for TST-NI-014 is implemented by
`scripts/visual_baseline.py`, while broad gallery health remains independently
enforced by `scripts/visual_health_smoke.py`.

`v1.json` is a bounded, versioned identity oracle for grouped bars, heatmap,
and composed layers. It stores exact rendered semantics and a checksummed
10×-downsampled RGB raster. The manifest pins the exact Playwright Chromium
version, repository font and SHA-256, 900×470 viewport, DPR 1, and explicit
geometry and perceptual tolerances. This is intentionally separate from the
all-gallery health smoke.

Every gate run must reject four real-browser negative controls:

- corrupted numeric payload values;
- wrong mark colors;
- changed rendered labels; and
- shifted/scaled geometry.

Failures retain expected, actual, full-resolution actual, diff, and semantic
artifacts. CI cannot update the manifest.

## Update policy

Install the pinned development browser tooling with `make setup-browser`, then
prepare a proposal with the exact Playwright executable:

```bash
CHROMIUM="$(node -e "const {chromium}=require('playwright'); process.stdout.write(chromium.executablePath())")"
python scripts/visual_baseline.py "$CHROMIUM" --update-baselines \
  --prepared-by "Your Name" --reason "intentional renderer change" \
  --artifacts visual-baseline-review
```

An update is not approval. Commit the manifest only alongside the intentional
renderer/spec change, attach `visual-baseline-review/` to the pull request, and
request an independent reviewer. The reviewer must inspect expected/actual/diff
PNGs and semantic JSON (`expected` is the prior reviewed baseline and `actual`
is the proposal), confirm the fixture and visual change are intended, and
reject unexplained browser/font pin or tolerance changes. Never regenerate the
file solely to turn an unexplained failure green.
