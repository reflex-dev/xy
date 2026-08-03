# Release Operator Checklist

Use this checklist to cut the `xy` distribution, including its bundled
`reflex_xy` integration. The production invariants behind these steps live in
[`production-readiness.md`](production-readiness.md); this document is the
ordered procedure for release operators.

## Safety rules

- The `vX.Y.Z` Git tag is the package version. There is no version file to
  edit.
- PyPI versions and uploaded files are immutable. If the version exists on
  PyPI, do not move its tag or rebuild different artifacts under that version.
- A GitHub release can be recreated under the same version only when PyPI
  confirms that no file for the version was uploaded.
- A partially published PyPI release must be retried from the same tag and
  commit. The publisher skips files PyPI already accepted.

## 1. Choose the version

Use a final or canonical PEP 440 prerelease tag:

```text
vX.Y.Z
vX.Y.ZaN
vX.Y.ZbN
vX.Y.ZrcN
```

Confirm the version does not already exist on PyPI:

```bash
curl --fail https://pypi.org/pypi/xy/X.Y.Z/json
```

A `404` means the version is unused. A successful response means the version
cannot be reused.

Inspect GitHub for an existing release or tag with the same name. Record where
any existing tag points and whether the release has assets before changing it.

## 2. Prepare the release commit

- Add a dated `## [X.Y.Z] — YYYY-MM-DD` entry to `CHANGELOG.md`.
- Confirm the changelog describes every user-visible change since the previous
  release.
- Refresh benchmark reports, or record why the previous report still applies.
- Run `make check-full`, or confirm the equivalent required CI checks passed.
- Run `make check-ci` after any workflow or release-wiring change.
- Run `make check-sdist` and `make check-wheel` after packaging changes.
- Run `make check-import` after changing lazy imports, backend loading, or the
  `reflex_xy` boundary.
- Run the release workflow manually with its default `dry_run: true` before the
  first release after changing the platform matrix, cross-compile toolchain,
  PyEmscripten ABI, or tag/version scheme.

The release pull request must be ready for review, have every actionable review
thread resolved, and pass all required checks before merge.

## 3. Verify both sdist installation contracts

The same freshly built sdist must prove both supported paths. Disable caches so
an old wheel cannot hide a broken source archive.

### Rust-backed installation

The release workflow installs a pinned Rust toolchain and installs the sdist
with `XY_REQUIRE_CARGO=1`. The smoke must:

- compile the native core with Cargo;
- import `xy`, `reflex_xy`, and `xy.kernels` from the installed distribution;
- confirm package metadata, `xy.__version__`, and `reflex_xy.__version__`
  agree; and
- assert `xy.kernels.BACKEND == "native"`.

Representative local installation:

```bash
XY_REQUIRE_CARGO=1 uv pip install --no-cache dist/xy-X.Y.Z.tar.gz
```

### Coreless installation

A separate environment installs the same sdist with `XY_SKIP_CARGO=1`. It
must:

- import `xy` and `reflex_xy` without NumPy, Reflex, or the native core being
  loaded eagerly;
- report matching versions; and
- raise the documented native-core `ImportError` only when compute is
  requested.

Representative local installation:

```bash
XY_SKIP_CARGO=1 uv pip install --no-cache dist/xy-X.Y.Z.tar.gz
```

Tests that exercise the optional Reflex integration must not make the base
Python-floor job install Reflex. Gate those integration-only assertions with
`pytest.importorskip("reflex")`.

## 4. Merge and record the release commit

After the release PR merges:

1. Fetch the latest `main`.
2. Confirm the merge commit contains the changelog and release changes.
3. Record the full commit SHA.
4. Confirm no later commit has moved `main` before selecting the release
   target.

Do not tag a pre-merge branch or a commit with incomplete required checks.

## 5. Publish the GitHub release

In **GitHub → Releases → Draft a new release**:

1. Create `vX.Y.Z` from the recorded release commit on `main`.
2. Set the title to `vX.Y.Z`.
3. Generate notes from the previous library release tag.
4. Confirm the notes include both the release PR and any release-fix PRs.
5. Select **Latest** for a production release, or the prerelease label for a
   prerelease.
6. Publish the release.

Publishing creates the tag and triggers `.github/workflows/release.yml`. Check
the release page immediately and confirm its displayed commit is the recorded
SHA.

## 6. Monitor every release job

Find and watch the run:

```bash
gh run list --repo reflex-dev/xy --workflow release.yml --limit 5
gh run watch RUN_ID --repo reflex-dev/xy --compact --exit-status
```

Do not call the release complete until all of these pass:

- sdist structural verification;
- Rust-backed sdist build and native import;
- coreless sdist lightweight-import and clear-error smoke;
- native macOS wheels for x86-64 and Apple Silicon;
- native Windows wheels for x86, x64, and arm64;
- manylinux and musllinux wheels for every supported architecture;
- PyEmscripten build and real Pyodide runtime load smoke; and
- trusted PyPI publication.

The GitHub release may show only GitHub's source archives. The distribution
wheels and sdist are published to PyPI by the workflow.

## 7. Verify PyPI from a clean environment

Confirm PyPI exposes the version and expected files:

```bash
curl --fail https://pypi.org/pypi/xy/X.Y.Z/json
```

Create a new environment outside the repository so the checkout cannot shadow
the installed package:

```bash
TMP_DIR=$(mktemp -d /private/tmp/xy-release-smoke.XXXXXX)
UV_CACHE_DIR="$TMP_DIR/uv-cache" uv venv "$TMP_DIR/.venv" --python 3.12
UV_CACHE_DIR="$TMP_DIR/uv-cache" uv pip install \
  --python "$TMP_DIR/.venv/bin/python" \
  --no-cache \
  'xy[reflex]==X.Y.Z' \
  numpy
```

Verify versions, import locations, and the backend:

```python
import importlib.metadata as metadata

import reflex_xy
import xy
import xy.kernels as kernels

assert metadata.version("xy") == "X.Y.Z"
assert xy.__version__ == "X.Y.Z"
assert reflex_xy.__version__ == "X.Y.Z"
assert kernels.BACKEND == "native"

print(xy.__file__)
print(reflex_xy.__file__)
```

Both paths must point into the clean environment's `site-packages`.

## 8. Run published-package examples

Exercise more than imports. From the clean environment:

- build the README line chart and export non-empty HTML and SVG files;
- build the first-chart scatter and export self-contained HTML;
- render a pyplot sine chart to a valid, non-empty PNG; and
- construct a `reflex_xy.chart(...)` component and confirm it returns an
  `XYChart`.

These checks cover the declarative API, generated client bundle, native static
export, pyplot compatibility layer, and bundled Reflex integration from the
actual PyPI artifact.

## 9. Create the release video and thumbnail

Prepare the release media only after the published package and examples pass
verification. Use the final release URL and output generated by the released
version:

```text
RELEASE_URL: https://github.com/reflex-dev/xy/releases/tag/vX.Y.Z
BRAND_URL: https://reflex.dev
PRODUCT_NAME: XY
TARGET_PLATFORM: LinkedIn
DURATION: 15–30 seconds
```

Build the video with Remotion at 1920×1080 and 30 fps. The final edit must be
specific to this release, communicate clearly with sound muted, and follow the
current `reflex.dev` visual system: a clean near-white canvas, charcoal
typography, faint lavender grid lines, restrained purple and green accents,
thin borders, and subtle shadows.

Music and subtle sound effects are optional, but every essential point must
appear on screen.

### Research and content

- Read the complete release notes and every linked example used in the video.
- Select the three or four most visually compelling release improvements.
- Verify every feature name, statistic, installation command, and performance
  claim. Never invent metrics or features.
- Use actual output from the released version for charts, components, and UI
  examples whenever it is available.
- Give every highlight a short headline, a visual demonstration where
  possible, and one concise supporting detail.

Charts must look production-quality and remain completely visible. Do not crop
axes, labels, legends, nodes, flows, or chart boundaries. Keep the motion
energetic and technical without making the composition cluttered. Include a
polished animated product logo at both the beginning and the end.

### Suggested timeline

1. **0–3 seconds:** show the XY logo, release number, and a strong release
   hook.
2. **3–17 seconds:** demonstrate the main visual features with clear labels
   and enough screen time to understand each one.
3. **17–22 seconds:** show verified performance, package-size, compatibility,
   or developer-experience improvements.
4. **22–26 seconds:** summarize the highlights and finish with the exact
   installation command or release URL.

### Required deliverables

- an H.264 MP4 suitable for LinkedIn, between 15 and 30 seconds long;
- a separate 1920×1080 LinkedIn thumbnail PNG;
- complete Remotion source;
- a concise LinkedIn description with the release link and relevant hashtags;
  and
- a contact sheet or representative full-resolution frames for review.

The thumbnail must match `reflex.dev`, include **XY X.Y.Z RELEASE**, list all
major highlights in readable labels, and feature the strongest chart or
product visual prominently. Additional charts are welcome when useful, but
every chart must remain fully visible and uncropped. Avoid black frames,
generic video stills, and dark panels on the light background.

### Quality and approval gate

- Run the TypeScript checks and complete a final Remotion render.
- Inspect several full-resolution frames from every scene.
- Confirm all text is readable and no content is clipped.
- Confirm every chart accurately represents the released library.
- Confirm the finished duration is between 15 and 30 seconds.
- Show the final video, thumbnail, and representative frames to the release
  owner for review.
- Do not upload, publish, or schedule anything until the release owner
  explicitly replies **“approve.”**

## Recovery procedures

### The workflow failed before any PyPI upload

Fix the failure in a PR and merge it. If the version must be reused:

1. Confirm the PyPI JSON endpoint still returns `404`.
2. Obtain explicit confirmation before deleting the public GitHub release or
   tag.
3. Delete the stale GitHub release first; GitHub disables tag deletion while a
   release owns it.
4. Delete the stale tag.
5. Recreate the release and tag at the corrected merge commit.

Never force-move the tag if PyPI accepted any artifact.

### PyPI accepted only some files

Keep the tag and commit unchanged. Rerun the same release workflow. Its
publisher uses `skip-existing` so accepted files remain immutable while the
missing artifacts are uploaded.

### The Python floor fails because Reflex is missing

The base floor intentionally excludes optional extras. Use
`pytest.importorskip("reflex")` for Reflex-only tests rather than weakening the
base-package dependency boundary.

### Local socket tests fail with `PermissionError`

Check whether the test is running in a sandbox that forbids localhost binding.
Rerun the relevant test in an environment where loopback sockets are allowed
before treating it as a product regression.

## Final sign-off

- [ ] The version was unused on PyPI before tagging.
- [ ] The dated changelog entry matches the tag.
- [ ] Required CI and review checks passed on the release commit.
- [ ] The tag points at the recorded merge commit.
- [ ] Native and coreless sdist contracts passed from the same source archive.
- [ ] Every native and PyEmscripten wheel passed verification.
- [ ] Trusted publication completed successfully.
- [ ] PyPI exposes the expected version and artifacts.
- [ ] A clean install reports matching `xy` and `reflex_xy` versions.
- [ ] The clean install loads `xy.kernels.BACKEND == "native"`.
- [ ] Declarative, export, pyplot, and Reflex examples passed from
  `site-packages`.
- [ ] Release video, thumbnail, source, LinkedIn copy, and review frames passed
  the quality checks.
- [ ] The release owner explicitly approved the media before publication or
  scheduling.
