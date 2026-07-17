---
title: Installation
description: Install XY, understand its bundled runtime, and choose optional integrations.
---

# Installation

XY supports Python 3.11 and newer. Add it with your preferred package manager:

~~~~md tabs
## uv

~~~bash
uv add xy
~~~

## pip

~~~bash
python -m pip install xy
~~~
~~~~

Confirm the package imports from the environment where your code will run:

~~~bash
python -c "import xy; print(xy.__version__)"
~~~

## What the package includes

The regular `xy` dependency already includes NumPy and anywidget support.
Published platform wheels bundle the Python package, browser client, and native
Rust compute core. Notebook display and HTML, native PNG, and SVG export do not
require separate `notebooks` or `export` extras, Node, npm, or a CDN.

A source install must compile the required native core and therefore needs a
Rust toolchain. On a platform without a compatible wheel or a successful source
build, XY raises an actionable import error instead of silently switching to a
slower implementation.

## Optional tools and integrations

- Install `pyarrow` separately when you want Arrow-backed input:

  ~~~bash
  uv add pyarrow
  ~~~

- Install the separate Reflex adapter for state-backed application charts:

  ~~~bash
  uv add reflex-xy
  ~~~

  Continue with the [Reflex integration guide](/docs/xy/integrations/reflex/).

- Native PNG is the default static raster path and does not launch a browser.
  Chromium-based PNG export is optional and discovers Chrome, Chromium, Edge,
  or `chrome-headless-shell` on the machine; set `XY_BROWSER` to an executable
  path when automatic discovery is not appropriate.

Next, build [your first chart](/docs/xy/overview/first-chart/).
