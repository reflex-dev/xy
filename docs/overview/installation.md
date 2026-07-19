---
title: Installation
description: Install XY, understand its bundled runtime, and choose optional integrations.
---

# Installation

XY 0.0.1 supports Python 3.11 and newer. Install the released core package
from PyPI with your preferred package manager:

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

## Supported platforms

XY supports the platforms below. The PyPI column describes only the files in
the current 0.0.1 upload, not whether XY supports the platform.

| Platform | Compatibility | Architectures | XY support | PyPI 0.0.1 wheel |
| --- | --- | --- | --- | --- |
| macOS | macOS 10.12+ on Intel; macOS 11+ on Apple silicon | `x86_64`, `arm64` | Supported | Included |
| Linux | glibc (`manylinux_2_17`) | `x86_64`, `aarch64`, `armv7l` | Supported | Included |
| Linux | musl (`musllinux_1_2`, including Alpine) | `x86_64`, `aarch64`, `armv7l` | Supported | Included |
| Windows | Native Windows | `x86_64`, `x86`, `arm64` | Supported | Not included |
| WebAssembly | Pyodide 0.29.4 (Emscripten) | `wasm32` | Supported | Not accepted by PyPI |

Windows is supported by XY's native core and release pipeline. The current
0.0.1 PyPI upload does not include Windows wheels or a source distribution, so
`uv add xy` and `python -m pip install xy` cannot install it directly on
Windows yet. Until a Windows wheel is published, install the tagged source
with a Rust MSVC toolchain as described below.

WebAssembly is supported through a runtime-verified Pyodide wheel for
in-browser Python. PyPI does not accept its `pyodide_2025_0_wasm32` platform
tag, so the WASM wheel is not available through the normal install commands.
This target runs XY's Python and Rust core inside Pyodide; it is separate from
the JavaScript/WebGL client included with every chart.

## What the package includes

The regular `xy` dependency already includes NumPy and anywidget support.
Published platform wheels bundle the Python package, browser client, and native
Rust compute core. Notebook display and HTML, native PNG, and SVG export do not
require separate `notebooks` or `export` extras, Node, npm, or a CDN.

## Installing from Git or source

Use the PyPI wheel when your platform is supported. A working source install
must compile the native compute core, so it requires a Rust toolchain with
`cargo` and `rustc`. The browser client is committed to the repository; Node
and npm are not required just to install it.

To reproduce the 0.0.1 release from Git with uv:

~~~bash
uv add "xy @ git+https://github.com/reflex-dev/xy.git@v0.0.1"
~~~

Or install the same tagged source with pip:

~~~bash
python -m pip install "xy @ git+https://github.com/reflex-dev/xy.git@v0.0.1"
~~~

A source build without Rust can finish installing, but it has no compute
backend and fails with an actionable error when a chart first needs native
compute. XY does not silently switch to a slower implementation. Building for
an unsupported operating system or architecture may also require target-specific
Rust tooling beyond the commands above.

## Optional tools and integrations

- Install `pyarrow` separately when you want Arrow-backed input:

  ~~~bash
  uv add pyarrow
  ~~~

- The separate Reflex adapter supports state-backed application charts, but it
  is experimental and is not published on PyPI. Opt in by pairing the released
  `xy` core with the adapter from the matching `v0.0.1` Git tag. With uv:

  ~~~bash
  uv add "xy==0.0.1" "reflex-xy @ git+https://github.com/reflex-dev/xy.git@v0.0.1#subdirectory=python/reflex-xy"
  ~~~

  Or with pip:

  ~~~bash
  python -m pip install "xy==0.0.1" "reflex-xy @ git+https://github.com/reflex-dev/xy.git@v0.0.1#subdirectory=python/reflex-xy"
  ~~~

  The tag keeps the unreleased adapter aligned with the public 0.0.1 core.
  Continue with the [Reflex integration guide](/docs/xy/integrations/reflex/)
  for its current limitations and setup.

- Native PNG is the default static raster path and does not launch a browser.
  Chromium-based PNG export is optional and discovers Chrome, Chromium, Edge,
  or `chrome-headless-shell` on the machine; set `XY_BROWSER` to an executable
  path when automatic discovery is not appropriate.

Next, build [your first chart](/docs/xy/overview/first-chart/).
