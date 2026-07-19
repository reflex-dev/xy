---
title: Deployment Recipes
description: Ship standalone HTML and images, prepare offline wheels, and understand the CSP and Reflex boundaries.
---

# Deployment Recipes

Choose deployment from the behavior that must remain after Python exits. A
standalone HTML file keeps browser-local interaction. PNG and SVG are static
artifacts. Python callbacks, future appends, and state-derived data require a
live host integration.

The recipes below use the released `xy` core package only unless a section is
explicitly marked otherwise.

## Publish one interactive HTML file

Create `build_report.py`:

~~~python
from pathlib import Path

import xy

chart = xy.line_chart(
    xy.line([1, 2, 3, 4], [12, 18, 15, 23], name="orders", color="#2563eb"),
    xy.x_axis(label="week"),
    xy.y_axis(label="orders"),
    xy.legend(),
    title="Weekly orders",
    width=900,
    height=420,
)

destination = Path("site/charts/weekly-orders.html")
destination.parent.mkdir(parents=True, exist_ok=True)
chart.to_html(destination)
print("wrote", destination)
~~~

Build and preview it through a local static server:

~~~bash
python build_report.py
python -m http.server 8000 --directory site
~~~

Open `http://127.0.0.1:8000/charts/weekly-orders.html`. Upload the `site/`
directory to an ordinary static host to publish it. The HTML contains the XY
client, chart specification, and data needed for hover, pan, zoom, selection,
and built-in controls; it does not call a Python process after export.

Treat the file as a data artifact. Anyone who can download it can inspect the
embedded chart data, so do not export secrets or row-level data that the
viewer is not allowed to receive.

## Publish native PNG and SVG assets

Add static outputs after constructing the same `chart`:

~~~python
assets = Path("site/assets")
assets.mkdir(parents=True, exist_ok=True)

chart.to_png(str(assets / "weekly-orders.png"), width=1200, height=630, scale=2)
chart.to_svg(assets / "weekly-orders.svg", width=1200, height=630)
~~~

The default PNG path is the browser-free native renderer bundled with a
compatible XY wheel. Use explicit dimensions for repeatable report, social,
and test output. Use Chromium export only when browser fonts, injected CSS, or
WebGL fidelity is a requirement; see
[Display and export](/docs/xy/guides/display-and-export/) for that optional
engine and its local browser dependency.

## Build a pinned Docker image

Keep the package version explicit and choose a base image that has a published
wheel for its operating system and architecture:

~~~dockerfile
FROM python:3.11-slim

ARG XY_VERSION=0.0.1

WORKDIR /app
RUN python -m pip install --no-cache-dir "xy==${XY_VERSION}"

COPY build_report.py /app/build_report.py

CMD ["python", "build_report.py"]
~~~

Build and copy the generated artifacts out of a container:

~~~bash
docker build --build-arg XY_VERSION=0.0.1 -t xy-report:0.0.1 .
docker run --rm -v "$PWD/site:/app/site" xy-report:0.0.1
~~~

Run this image as a build job, not as a server: the script produces static
artifacts and exits. If `pip` cannot find a compatible binary wheel, stop and
check the [installation boundary](/docs/xy/overview/installation/) rather than
silently changing the target platform.

## Prepare an air-gapped wheelhouse

On a connected machine that matches the target Python, operating system, and
architecture, download XY and all of its Python dependencies:

~~~bash
mkdir -p wheelhouse
python -m pip download \
  --only-binary=:all: \
  --dest wheelhouse \
  "xy==0.0.1"
~~~

Transfer the complete `wheelhouse/` directory through the approved channel.
Inside the disconnected environment:

~~~bash
python -m pip install \
  --no-index \
  --find-links wheelhouse \
  "xy==0.0.1"

python -m pip check
python -c "import xy, xy.kernels as k; print(xy.__version__, k.BACKEND)"
~~~

Use an internal package index instead of a directory when that is your
organization's standard control point. Mirror each platform wheel you deploy;
a wheel downloaded for one target is not evidence that another target is
covered. Native PNG, SVG, and standalone HTML need no network after the wheel
is installed. Chromium PNG additionally needs a compatible browser already
present in the environment.

## Respect the CSP boundary

`chart.to_html()` optimizes for a portable single file. Its emitted policy
blocks external connections but permits the inline script and style blocks
that make the file self-contained, plus a `blob:` worker used by applicable
rendering paths.

That means there are two distinct deployment choices:

1. Serve the standalone document as its own page under the policy it emits.
2. If the host requires nonce- or hash-only scripts and styles, build an
   application wrapper that serves the XY client separately and injects data
   through the host's approved path.

Do not iframe or paste the standalone document into a stricter application and
assume the policies will merge into a working configuration. Follow
[Serving, CSP, and offline use](/docs/xy/guides/serving-csp-and-offline-use/)
for the current directives and security tradeoffs, and test the final response
headers rather than only opening the file locally.

## Reflex live applications depend on an unreleased adapter

The [Reflex integration path](/docs/xy/integrations/reflex/) describes fixed,
live-token, and state-backed application tiers, but it depends on the separate
`reflex-xy` adapter. That adapter is experimental and is not currently a
published package, so the integration guide is a preview rather than an
installable production recipe.

Until a released adapter version is available, use core XY's standalone HTML,
PNG, or SVG outputs, or evaluate the adapter from source in a pinned test
environment. Do not place `pip install reflex-xy` in production automation and
assume it resolves from the public package index. When it is released, pin
both `xy` and `reflex-xy`, test their documented compatibility, and then follow
the live deployment boundary in the integration guide.

For the capability-level decision, see
[Choosing a runtime and deployment mode](/docs/xy/advanced/runtime-and-deployment/).
For failures in a target environment, use
[Getting help](/docs/xy/guides/getting-help/).
