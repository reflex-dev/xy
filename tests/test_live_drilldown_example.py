"""The live-drilldown example ships window-appropriate points at every zoom.

The example's local integral-image fast path answers wide/mid windows without
a server round trip, but the integral image holds only counts — those replies
used to ship no point sample, so nothing refined between the home overview
and the server's exact-scan threshold ("no drilldown points until >600%
zoom"). The example now embeds a deterministic global presample (real rows
with the trace's color/size channels) and attaches the in-window subset to
every locally served density reply; the engine's T9 window pairing draws it.

Pure-python checks (no server, no browser): presample determinism and unit
normalization, and the generated page carrying the presample machinery.
Runs against a small XY_LIVE_POINTS so the 100M default doesn't build here.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "examples" / "fastapi" / "live_drilldown.py"


@pytest.fixture(scope="module")
def drilldown():
    """Load the example by file path (no sys.path games — `examples/fastapi/`
    must never shadow the real fastapi package for the rest of the suite),
    with a small XY_LIVE_POINTS so the 100M default doesn't build here."""
    old = os.environ.get("XY_LIVE_POINTS")
    os.environ["XY_LIVE_POINTS"] = "200000"
    try:
        spec = importlib.util.spec_from_file_location("_live_drilldown_example", _MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        # dataclass field resolution looks the class's module up by name.
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop("_live_drilldown_example", None)
        if old is None:
            os.environ.pop("XY_LIVE_POINTS", None)
        else:
            os.environ["XY_LIVE_POINTS"] = old


def test_presample_is_deterministic_and_unit_normalized(drilldown) -> None:
    store = drilldown.live_store()
    ps = store.presample
    n = len(ps.x)
    assert 0 < n <= drilldown.PRESAMPLE_TARGET
    assert len(ps.y) == len(ps.color) == len(ps.size) == n
    # Channels ship unit-normalized, like every continuous channel on the wire.
    for arr in (ps.color, ps.size):
        assert arr.dtype == np.float32
        assert float(arr.min()) >= 0.0
        assert float(arr.max()) <= 1.0
    # Deterministic: rebuilding from the same figure selects the same rows
    # (§28 anti-shimmer — the same window must always show the same points).
    again = drilldown.Presample.build(store.figure)
    assert np.array_equal(ps.x, again.x)
    assert np.array_equal(ps.y, again.y)
    # The rows are real source rows.
    t = store.figure.traces[0]
    assert float(ps.x[0]) == pytest.approx(float(t.x.values[0]), rel=1e-6)


def test_drilldown_page_embeds_presample_machinery(drilldown) -> None:
    html = drilldown.live_drilldown_html()
    # The page carries the presample data + the in-window selector, and the
    # locally synthesized density replies attach the sample for T9 pairing.
    for marker in (
        "PRESAMPLE_META",
        "function presampleWindow(",
        "sample: pts.n",
        "buffers: [grid.buffer, pts.xs.buffer, pts.ys.buffer, pts.cs.buffer, pts.ss.buffer]",
    ):
        assert marker in html, f"drilldown page lost presample marker {marker!r}"
