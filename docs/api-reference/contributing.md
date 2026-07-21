---
title: Contributing
description: Set up XY development, run the right gates, and prepare a focused change.
---

# Contributing

XY welcomes focused bug fixes, documentation improvements, tests, and chart
surface work. The canonical contributor guide is
[CONTRIBUTING.md](https://github.com/reflex-dev/xy/blob/main/CONTRIBUTING.md);
the internal [contributor specification](https://github.com/reflex-dev/xy/blob/main/spec/contributing.md)
contains the complete release and browser checklists.

## Local Setup

~~~bash
git clone https://github.com/reflex-dev/xy.git
cd xy
make setup
make check
~~~

`make setup` installs the editable development package and builds the required
native core. Source development needs Python 3.11+, a Rust toolchain for that
core, and Node 18+ for bundle checks. Confirm the active compute backend
explicitly:

~~~bash
python -c "import xy.kernels as k; print(k.BACKEND)"
~~~

The supported value is `native`. An unavailable core should raise a clear
import error rather than silently selecting another backend.

## Choose the Focused Gate

| Change | Check |
| --- | --- |
| Fast local verification | `make check` |
| Production-facing change | `make check-full` |
| Public docs, examples, or claims | `make check-docs` |
| Public exports or annotations | `make check-api` |
| Lazy imports and dependency boundaries | `make check-import` |
| Validation and mutation behavior | `make check-errors` |
| Standalone HTML and text safety | `make check-security` |
| Browser lifecycle and interaction | `make check-browser CHROMIUM=/path/to/chrome` |

Run `make check-claims` before publishing performance prose. Every comparison
must name the chart type, data size and shape, representation mode, backend,
render target, and whether browser time-to-first-render is included.

## Adding a Chart Type

A complete chart-family contribution normally spans:

1. Builder validation and rollback tests.
2. Canonical column ingest or an aggregate kernel.
3. Payload metadata with an explicit direct, decimated, density, sampled, or
   adaptive mode.
4. Renderer support or reuse of an existing primitive.
5. Standalone/export coverage, including hostile text values.
6. A declarative factory and generated API documentation.
7. A normal-size visual example, plus a benchmark only when the methodology is
   honest and reproducible.

Keep generated assets derived from their source generator, preserve lazy
`import xy` behavior, and include new public symbols in `xy.__all__` with type
surface tests.

Before opening a pull request, read the relevant architecture material in the
repository and open a focused
[GitHub issue](https://github.com/reflex-dev/xy/issues/new) when the desired
behavior changes a public contract.
