# Host Compatibility

XY supports a bounded set of host-library versions. The executable source of
truth is [`../testing/host-integration-policy.json`](../testing/host-integration-policy.json);
package metadata must declare the same ranges, and
`scripts/host_integration_policy.py validate` fails when they diverge. A new
major version is outside the supported range until a reviewed change widens the
policy and runs the expanded matrix.

## Supported versions

| Host surface | Package | Supported range | CI floor |
|---|---|---|---|
| Anywidget | `anywidget` | `>=0.9,<1` | `0.9.0` |
| Anywidget trait transport | `traitlets` | `>=5.14,<6` | `5.14.0` |
| Reflex adapter | `reflex` | `>=0.9.6,<1` | `0.9.6` |
| FastAPI example | `fastapi` | `>=0.110,<1` | `0.110.0` |
| FastAPI ASGI layer | `starlette` | `>=0.36.3,<1` | `0.36.3` |
| FastAPI production server | `uvicorn` | `>=0.29,<1` | `0.29.0` |
| FastAPI in-process transport | `httpx` | `>=0.27,<1` | `0.27.0` |

`pyproject.toml` owns the Anywidget runtime declarations and the FastAPI test
stack. `python/reflex-xy/pyproject.toml` owns the Reflex declaration.
`examples/fastapi/pyproject.toml` owns every library that its application or
focused host tests import directly. Transitive installation alone does not
count as support metadata.

## Executable matrix

Every pull request runs two hard profiles on Python 3.13:

- `floor` installs every exact floor above; and
- `latest` resolves the newest mutually compatible release inside every
  supported range.

The `host_integration` job builds the locked native core, verifies the committed
client is fresh, then runs `tests/host_integration/` through
`scripts/run_pytest_no_skips.py`. It
compiles the FastAPI example, mounts its routes through `TestClient`, exercises
HTTP drilldown transport, instantiates the real `AnyWidget`, and drives split
binary comm messages. `scripts/fastapi_host_smoke.py` starts Uvicorn with the
matrix interpreter, requires a nonblank WebGL2 canvas, and sends the drilldown
request from Chromium. The job retains installed-version JSON, JUnit, browser
JSON, a screenshot, and the server log for both profiles.

The package-owned `reflex_adapter` job independently installs the Reflex floor
or latest supported release. It records the installed version, runs the adapter
suite with zero skips, compiles and starts the production example, and proves
the browser/socket transport. It retains the version report, JUnit, server log,
and screenshot for each profile.

| Host | Compile | Mount | Transport | Browser |
|---|---|---|---|---|
| Anywidget | Widget construction and bundled ESM contract | Real Python `AnyWidget` trait model | Pick reply and binary append comm buffers | Not claimed here; a real notebook frontend remains TST-NI-018 |
| Reflex | Production example compile | Production Reflex application | Shared socket, state, stream, and close behavior | Real Chromium paint and interaction |
| FastAPI/Starlette | Every example module | In-process routes and current-environment Uvicorn | Health, chart, and drilldown requests | Real Chromium WebGL2 paint and browser-originated drilldown |

The matrix has no optional-import or browser skip path. A missing dependency,
unsupported installed version, skipped test, blank canvas, failed transport, or
missing evidence artifact fails the hard `required_ci` aggregate.

## Boundary

This contract proves the declared Python host seams at both supported edges. It
does not claim that a JupyterLab or classic-notebook frontend mounts the widget;
that separate real-frontend lifecycle and bidirectional E2E remains tracked by
TST-NI-018 in [`../testing/gaps.md`](../testing/gaps.md).
