"""A chart rendering in a real browser over the Reflex channel transport.

The rest of the adapter suite drives the data plane from Python. This one
proves the thing that only a browser can: the wrapper opens no connection of
its own, the app's single websocket carries the chart's binary columns, and
the WebGL view paints from them.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

# This is the only check of the single-shared-websocket claim, so a missing
# browser must not quietly turn it into a pass. `XY_REQUIRE_BROWSER` — which CI
# sets — makes both the Python package and the browser binary hard
# requirements; without it a bare checkout still skips. Read for truthiness,
# not for the literal "1", so this gate opens on exactly the same values as the
# sibling one in tests/conftest.py: a mismatch there would fail every other
# browser probe while leaving this one skipping.
REQUIRE_BROWSER = bool(os.environ.get("XY_REQUIRE_BROWSER"))
if not REQUIRE_BROWSER:
    pytest.importorskip("playwright")

from PIL import Image  # noqa: E402
from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import WebSocket, sync_playwright  # noqa: E402
from reflex.testing import AppHarness  # noqa: E402

from reflex_xy.data_plane import XY_PLANE  # noqa: E402

# The app's event websocket, the one the chart has to share.
EVENT_PATH = "/_event"

# Headless chromium has no GPU; xy's own browser probes use the same pair.
CHROMIUM_ARGS = ("--use-angle=swiftshader", "--enable-unsafe-swiftshader")

# Where to keep the painted-chart screenshot. CI points this at an uploaded
# artifact directory so the evidence outlives the run; locally it defaults to
# pytest's tmp_path.
EVIDENCE_DIR = os.environ.get("XY_BROWSER_EVIDENCE")


def ChannelChartApp():
    """A Reflex app with one live xy chart served over a channel."""
    import numpy as np
    import reflex as rx

    import reflex_xy
    import xy

    def orbits() -> "xy.Chart":
        rng = np.random.default_rng(3)
        count = 20_000
        theta = rng.uniform(0.0, 2.0 * np.pi, count)
        radius = rng.normal(1.0, 0.05, count)
        return xy.scatter_chart(
            xy.scatter(radius * np.cos(theta), radius * np.sin(theta), opacity=0.6),
            xy.x_axis(label="x"),
            xy.y_axis(label="y"),
            width="100%",
            height=240,
        )

    token = reflex_xy.inline(orbits())

    @rx.page("/")
    def index():
        return rx.box(
            reflex_xy.chart(token, height="240px"),
            rx.text("ready", id="ready"),
        )

    app = rx.App()
    reflex_xy.setup(app)


@pytest.fixture
def _fresh_registry():
    """Keep the registry across this module's tests.

    The package-wide autouse fixture resets it between tests, but this app
    registers its figure once, when the harness imports it — a reset would
    leave the subscribe with no figure to serve.

    Yields:
        None; this only shadows the resetting fixture.
    """
    yield


@pytest.fixture(scope="module")
def chart_app() -> Generator[AppHarness, None, None]:
    """Build and serve the chart app.

    The root is a self-deleting temp dir rather than `tmp_path_factory`: a
    compiled Reflex app is ~200 MB of `node_modules` and `.web`, and pytest
    keeps its last three runs, so borrowing that retention would leave most of
    a gigabyte behind per run — enough to fill a tmpfs `/tmp` after an
    afternoon of local runs and make every *other* browser probe fail for want
    of space. CI gets one run per job either way.

    Yields:
        The running harness.
    """
    with (
        tempfile.TemporaryDirectory(prefix="xy-channel-chart-app-") as root,
        AppHarness.create(root=Path(root), app_source=ChannelChartApp) as harness,
    ):
        assert harness.app_instance is not None, "app is not running"
        yield harness


def test_chart_paints_from_channel_binary(chart_app: AppHarness, tmp_path: Path):
    """The chart paints, and its columns arrive on the app's own websocket.

    Args:
        chart_app: The running harness.
        tmp_path: Where to drop a screenshot of the painted chart.
    """
    assert chart_app.frontend_url is not None
    sockets: list[WebSocket] = []
    binary_frames: list[int] = []

    shot = Path(EVIDENCE_DIR or tmp_path) / "chart.png"
    shot.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(args=list(CHROMIUM_ARGS))
        except PlaywrightError as error:  # no browser binary installed
            if REQUIRE_BROWSER:
                raise
            pytest.skip(f"chromium is not installed for playwright: {error}")
        # Explicitly, rather than by leaving it to the sync_playwright exit: a
        # failing assertion inside the block would otherwise leave the Chromium
        # process up until the whole context unwinds, and those accumulate.
        try:
            page = browser.new_page(viewport={"width": 1024, "height": 768})

            def watch(socket: WebSocket) -> None:
                sockets.append(socket)
                if EVENT_PATH not in socket.url:
                    return  # the dev server's hot-reload channel
                socket.on(
                    "framereceived",
                    lambda payload: (
                        binary_frames.append(len(payload)) if isinstance(payload, bytes) else None
                    ),
                )

            page.on("websocket", watch)
            page.goto(chart_app.frontend_url)
            page.wait_for_selector("#ready")
            # The chart only reaches "ready" once a payload has been applied.
            # A cold dev server still has xy's WebGL client bundle to transform,
            # which outlasts the default wait by a wide margin.
            chart = page.locator('[data-xy-slot="root"]')
            chart.wait_for(state="visible", timeout=120_000)
            page.wait_for_function(
                "!!document.querySelector('[data-xy-context-state=\"ready\"]')",
                timeout=120_000,
            )
            # The accessible summary is computed from the decoded columns.
            summary = page.locator('[id$="-summary"]').inner_text()
            chart.screenshot(path=str(shot))
        finally:
            browser.close()

    # The chart opened nothing of its own. Checked first and by name, because
    # the count below cannot see it: a self-opened data plane would land on
    # some other URL and simply drop out of the filter.
    own_sockets = [socket.url for socket in sockets if XY_PLANE in socket.url]
    assert not own_sockets, f"the chart opened its own data plane socket: {own_sockets}"
    # One connection to the backend for the whole page: the chart multiplexes
    # onto the app's event websocket. (The other socket is the dev server's
    # hot-reload channel, which a built app does not have.)
    backend_sockets = [socket.url for socket in sockets if EVENT_PATH in socket.url]
    assert len(backend_sockets) == 1, backend_sockets
    # Columns travelled as binary frames on that socket, not as JSON numbers
    # or base64.
    assert binary_frames, "no binary frame arrived on the app websocket"
    assert max(binary_frames) > 10_000, (
        f"binary frames look too small for 20k points: {sorted(binary_frames)[-3:]}"
    )
    # Axis ranges in the accessible summary are derived from the columns, so
    # they only exist if the binary payload decoded into real data.
    assert "ranges from" in summary, summary
    # And the chart actually painted: a blank mount is one flat colour.
    with Image.open(shot) as image:
        colours = len(image.convert("RGB").getcolors(maxcolors=1 << 20) or [])
    assert colours > 50, f"chart looks blank: {colours} distinct colours"
    print(
        json.dumps(
            {
                "summary": summary.replace("\n", " ")[:120],
                "colours": colours,
                "binary_frames": binary_frames,
                "screenshot": str(shot),
            }
        )
    )
