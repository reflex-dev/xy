# Release Operator Checklist

Use this checklist to release the `xy` distribution, including its bundled
`reflex_xy` integration. The production invariants behind these steps live in
[`production-readiness.md`](production-readiness.md); this document is the
ordered procedure for release operators.

## Safety rules

- `CHANGELOG.md` is generated and is the release trigger. Do not hand-write a
  version heading.
- A `vX.Y.Z` tag records a successful publish; it does not start one. Never
  create, move, or push a release tag manually.
- PyPI versions and uploaded files are immutable. The publisher uses
  `uv publish --check-url` so a retry can preserve files PyPI already accepted
  while uploading any missing files.
- The `pypi` environment approval is the last human gate. Approve only the
  checksum manifest produced by the release being reviewed.

## 1. Prepare releasable changes

- Confirm every user-visible change under `python/`, `src/`, or `js/` has a
  towncrier fragment in `news/`, unless its pull request deliberately carries
  the `skip-changelog` label.
- Read the fragments as release notes: they should describe user impact rather
  than implementation details.
- Refresh benchmark reports, or record why the previous report still applies.
- Run `make check-full`, or confirm the equivalent required CI checks passed.
- Run `make check-ci` after any workflow or release-wiring change.
- Run `make check-sdist` and `make check-wheel` after packaging changes.
- Run `make check-import` after changing lazy imports, backend loading, or the
  `reflex_xy` boundary.

After changing the platform matrix, cross-compile toolchain, PyEmscripten ABI,
or tag/version scheme, exercise the full artifact matrix without entering a
publish path:

```bash
gh workflow run build_release_artifacts.yml \
  --repo reflex-dev/xy \
  --ref main \
  -f artifact-prefix=dry-run--
```

Leaving `tag` empty is the normal dry-run path. To test version derivation,
supply a valid **unused** tag: every matrix checkout fetches existing tags and
then creates the requested tag locally, so an existing release tag fails by
design. The local tag is never pushed. The manual workflow builds and verifies
artifacts only; it has no PyPI upload, tag-push, or GitHub release step.

## 2. Materialize the changelog

Run **Dispatch release** (`dispatch_release.yml`) from the Actions tab and pick
the intended action:

| Action | Result |
| --- | --- |
| `release-patch`, `release-minor`, `release-major` | Materializes a final version from `main` and opens a release pull request. |
| `release-post` | Materializes an `X.Y.Z.postN` packaging-only release and opens a release pull request. |
| `new-prerelease-patch`, `new-prerelease-minor`, `new-prerelease-major` | Starts an alpha train on an `r/pre-*` branch and immediately enters the release pipeline. |
| `continued-prerelease` | Materializes the next alpha on the current `r/pre-*` branch. |
| `release-from-prerelease` | Collapses the alpha sections into a final release section. |

Leaving the package checkbox clear auto-selects `xy` when it has pending news
fragments, or when an alpha-topped changelog is eligible for
`release-from-prerelease`.

For a final or post release:

1. Review the generated `CHANGELOG.md` section in the release pull request.
2. Confirm the version and notes are correct and no version heading was edited
   by hand.
3. Confirm every actionable review thread is resolved and all required checks
   pass.
4. Merge the release pull request. **The merge is what authorizes publishing.**

Prerelease actions push their materialized changelog directly to the release
branch. They still require the same PyPI environment approval before upload.

## 3. Review the build and approval gate

The push containing the new changelog heading starts
`release_from_changelog.yml`. It detects an untagged version and calls
`publish.yml`, which validates the release request and builds the complete
artifact set before asking for approval.

Watch the caller run:

```bash
gh run list \
  --repo reflex-dev/xy \
  --workflow release_from_changelog.yml \
  --limit 5
gh run watch RUN_ID --repo reflex-dev/xy --compact --exit-status
```

Open the called `publish.yml` run from the caller job. Before approving the
`pypi` environment deployment, confirm:

- every expected wheel and the sdist was collected;
- the run summary contains `SHA256SUMS` for exactly the files bound for PyPI;
- all build and verification jobs passed; and
- the version in the manifest matches the generated changelog section.

Approve the `pypi` environment only after that review. The gated job verifies
the manifest again, uploads with trusted publishing, and only then allows
`tag-and-release` to push the tag and create the GitHub release.

## 4. Verify both sdist installation contracts

The same freshly built sdist must prove both supported paths. Disable caches so
an old wheel cannot hide a broken source archive.

### Rust-backed installation

The release workflow installs the stable Rust toolchain and installs the sdist
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
- raise the documented native-core `ImportError` when `xy.kernels` is imported
  or the compute layer is touched, never at `import xy` or `import reflex_xy`.

Representative local installation:

```bash
XY_SKIP_CARGO=1 uv pip install --no-cache dist/xy-X.Y.Z.tar.gz
```

Tests that exercise the optional Reflex integration must not make the base
Python-floor job install Reflex. Gate those integration-only assertions with
`pytest.importorskip("reflex")`.

## 5. Confirm the published release

Do not call the release complete until all of these pass:

- sdist structural verification;
- Rust-backed sdist build and native import;
- coreless sdist lightweight-import and clear-error smoke;
- native macOS wheels for x86-64 and Apple Silicon;
- native Windows wheels for x86, x64, and arm64;
- manylinux and musllinux wheels for every supported architecture;
- PyEmscripten build and real Pyodide runtime load smoke;
- trusted PyPI publication;
- `tag-and-release`, including the GitHub release and attached checksum
  manifest; and
- the post-release docs deployment dispatch.

Confirm PyPI exposes the version and at least one file matching every artifact
pattern required by `[tool.reflex-release]`:

```bash
VERSION=X.Y.Z python3 - <<'PY'
import fnmatch
import json
import os
import tomllib
import urllib.request

version = os.environ["VERSION"]
request = urllib.request.Request(
    f"https://pypi.org/pypi/xy/{version}/json",
    headers={"User-Agent": "xy-release-checklist"},
)
with urllib.request.urlopen(request) as response:
    filenames = {item["filename"] for item in json.load(response)["urls"]}
with open("pyproject.toml", "rb") as pyproject:
    builds = tomllib.load(pyproject)["tool"]["reflex-release"]["custom-build"]
patterns = next(build["expect-artifacts"] for build in builds if "xy" in build["packages"])
missing = [pattern for pattern in patterns if not any(fnmatch.fnmatch(name, pattern) for name in filenames)]
assert not missing, f"PyPI is missing expected xy artifacts: {missing}"
print("\n".join(sorted(filenames)))
PY
```

Create a new environment outside the repository so the checkout cannot shadow
the installed package:

```bash
TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/xy-release-smoke.XXXXXX")
UV_CACHE_DIR="$TMP_DIR/uv-cache" uv venv "$TMP_DIR/.venv" --python 3.12
UV_CACHE_DIR="$TMP_DIR/uv-cache" uv pip install \
  --python "$TMP_DIR/.venv/bin/python" \
  --no-cache \
  'xy[reflex]==X.Y.Z' \
  numpy
```

Change to the temporary directory and invoke the environment's interpreter
explicitly so neither the checkout nor another Python installation can satisfy
the check:

```bash
cd "$TMP_DIR"
"$TMP_DIR/.venv/bin/python" - <<'PY'
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
PY
```

Both paths must point into the clean environment's `site-packages`.

## 6. Run published-package examples

Exercise more than imports. Run every example from `$TMP_DIR` with
`"$TMP_DIR/.venv/bin/python"`:

- build the README line chart and export non-empty HTML and SVG files;
- build the first-chart scatter and export self-contained HTML;
- render a pyplot sine chart to a valid, non-empty PNG; and
- construct a `reflex_xy.chart(...)` component and confirm it returns an
  `XYChart`.

These checks cover the declarative API, generated client bundle, native static
export, pyplot compatibility layer, and bundled Reflex integration from the
actual PyPI artifact.

## 7. Create the release video and thumbnail

Prepare release media only after the published package and examples pass
verification. Use the final release URL and output generated by the released
version:

```text
RELEASE_URL: https://github.com/reflex-dev/xy/releases/tag/vX.Y.Z
BRAND_URL: https://reflex.dev
PRODUCT_NAME: XY
TARGET_PLATFORM: LinkedIn
DURATION: 15–30 seconds
```

Build the video with Remotion at 1920×1080 and 30 fps. Make it specific to
the release and understandable with sound muted. Follow the current
`reflex.dev` visual system: a clean near-white canvas, charcoal typography,
faint lavender grid lines, restrained purple and green accents, thin borders,
and subtle shadows.

### Research and content

- Read the complete release notes and every linked example used in the video.
- Select the three or four most visually compelling release improvements.
- Verify every feature name, statistic, installation command, and performance
  claim. Never invent metrics or features.
- Use actual output from the released version whenever it is available.
- Keep every chart fully visible, including axes, labels, legends, nodes,
  flows, and chart boundaries.

### Required deliverables and approval

- an H.264 MP4 suitable for LinkedIn, between 15 and 30 seconds long;
- a separate 1920×1080 LinkedIn thumbnail PNG;
- complete Remotion source;
- a concise LinkedIn description with the release link and relevant hashtags;
- a contact sheet or representative full-resolution frames for review; and
- explicit release-owner approval before anything is uploaded, published, or
  scheduled.

Run the TypeScript checks and a final render, then inspect full-resolution
frames from every scene for readability, clipping, factual accuracy, and the
required duration.

## Recovery procedures

### Failure before any PyPI upload

No public tag or GitHub release exists yet. Fix the problem on top of the
changelog bump and merge or push it to the same release branch. The next push
causes `release_from_changelog.yml` to retry the same untagged version. A manual
dispatch of that workflow on the branch can also re-check it. Do not create a
tag or release to recover the run.

### PyPI accepted only some files, or the tag push failed

Leave every accepted PyPI file unchanged. Re-run the same release pipeline for
the same changelog version and commit. `uv publish --check-url
https://pypi.org/simple/` skips files already present and uploads any missing
ones. If no tag exists, `tag-and-release` can safely retry the tag push and
GitHub release. Never create or force-move the tag manually.

### The tag exists but GitHub release creation failed

The publish is complete and the tag is immutable. Do not rerun the changelog
pipeline: detection may no-op once it sees the tag. Download the failed run's
`publish-xy` artifact, which contains the exact `release_notes.md` and
`SHA256SUMS` produced before approval, then create the missing release from the
existing tag:

```bash
gh run download RUN_ID --repo reflex-dev/xy --name publish-xy
gh release create vX.Y.Z \
  --repo reflex-dev/xy \
  --verify-tag \
  --title vX.Y.Z \
  --notes-file release_notes.md \
  SHA256SUMS
```

Add `--prerelease` for a prerelease. Confirm the release targets the immutable
tag and contains the saved checksum manifest before manually dispatching the
post-release docs workflow if it did not run.

### The Python floor fails because Reflex is missing

The base floor intentionally excludes optional extras. Use
`pytest.importorskip("reflex")` for Reflex-only tests rather than weakening the
base-package dependency boundary.

### Local socket tests fail with `PermissionError`

Check whether the test is running in a sandbox that forbids localhost binding.
Rerun the relevant test in an environment where loopback sockets are allowed
before treating it as a product regression.

## Final sign-off

- [ ] News fragments covered every user-visible change before dispatch.
- [ ] The generated changelog section has the intended version and notes.
- [ ] Required CI and review checks passed on the release commit.
- [ ] The full artifact matrix and both sdist contracts passed.
- [ ] The checksum manifest matched exactly what the approver authorized.
- [ ] The `pypi` environment deployment was approved only after artifact
      review.
- [ ] Trusted publication completed successfully.
- [ ] The pipeline-created tag points at the published release commit.
- [ ] The GitHub release includes the release notes and checksum manifest.
- [ ] PyPI exposes the expected version and artifacts.
- [ ] A clean install reports matching `xy` and `reflex_xy` versions and loads
      `xy.kernels.BACKEND == "native"`.
- [ ] Declarative, export, pyplot, and Reflex examples passed from
      `site-packages`.
- [ ] The post-release docs deployment was dispatched or its failure was
      explicitly followed up.
- [ ] Release media passed quality review, and the release owner explicitly
      approved it before publication or scheduling.
