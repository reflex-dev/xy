"""Shared helpers for the browser-probe tests.

Plain functions (pytest puts this directory on ``sys.path``, so probe tests
import them with ``from conftest import run_browser_probe``).
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

# The `to_html` render call, whose shape the probe pages splice a view capture
# into. Exported so probe tests assert against one list instead of each keeping
# its own copy in sync with the exporter.
RENDER_CALLS = (
    'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
    'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
)


def probe_document(chart, probe: str, *, head: str = "") -> str:
    """A `to_html` page instrumented for a browser probe.

    Captures the live view as ``window.__fcProbeView`` (probe scripts drive it
    directly) and splices `probe` — plus any `head` markup, e.g. a page
    background the probe depends on — in before ``</body>``.
    """
    document = chart.to_html()
    render_call = next((call for call in RENDER_CALLS if call in document), None)
    assert render_call is not None, "to_html render call shape changed; update RENDER_CALLS"
    document = document.replace(
        render_call,
        render_call.replace(
            "xy.renderStandalone(", "window.__fcProbeView = xy.renderStandalone(", 1
        ),
        1,
    )
    return document.replace("</body>", head + probe + "\n</body>", 1)


def density_category_chart(n: int = 400_000, seed: int = 7):
    """A clustered 3-category density-tier scatter with a legend.

    The shared fixture behind the density legend probes: big enough to land on
    the density tier, clustered so each category owns a region of the
    mean-color plane. Returns ``(chart, cat, x, y)`` — the per-point code
    array and coordinates, for asserting masked counts and framing requests.
    """
    import xy

    rng = np.random.default_rng(seed)
    cat = rng.integers(0, 3, n)
    centers = np.array([[-1.2, -0.6], [0.2, 1.1], [1.5, -0.9]])
    x = rng.normal(centers[cat, 0], 0.4)
    y = rng.normal(centers[cat, 1], 0.4)
    labels = np.array(["A", "B", "C"])[cat]
    chart = xy.scatter_chart(
        xy.scatter(x, y, color=labels, density=True),
        xy.legend(),
        width=520,
        height=340,
    )
    return chart, cat, x, y


def _dump_dom(chromium: str, page: Path) -> str | None:
    """One headless render pass; None on a chromium-level failure (retryable)."""
    try:
        proc = subprocess.run(
            [
                chromium,
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--allow-file-access-from-files",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                "--hide-scrollbars",
                "--window-size=640,480",
                "--virtual-time-budget=8000",
                "--dump-dom",
                page.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return None
    return proc.stdout if proc.returncode == 0 else None


def run_browser_probe(
    chromium: str,
    document: str,
    page: Path,
    result_attribute: str,
    *,
    label: str,
) -> dict:
    """Render `document` headless and scrape one JSON probe result, with retries.

    The probe script reports success by JSON-encoding its payload into
    ``result_attribute`` on ``<body>`` and failure into
    ``{result_attribute}-error``. Returns the parsed result payload. If Chromium
    never returns a DOM the test is skipped as an environmental miss; once a
    DOM is returned, probe errors and missing results fail the test.

    Headless probes on shared runners have transient warm-up misses (virtual
    time / GL init) that a relaunch clears; a genuine regression fails every
    attempt with a *value* mismatch, which we surface — never retry away.
    """
    page.write_text(document, encoding="utf-8")
    last: str | None = None
    for _ in range(3):
        dom = _dump_dom(chromium, page)
        if dom is None:
            continue
        error = re.search(rf'{re.escape(result_attribute)}-error="([^"]*)"', dom)
        if error:
            last = f"probe error: {html.unescape(error.group(1))}"
            continue
        match = re.search(rf'{re.escape(result_attribute)}="([^"]*)"', dom)
        if match:
            return json.loads(html.unescape(match.group(1)))
        last = "probe did not finish (no result attribute)"
    if last:
        pytest.fail(f"{label} could not run after retries: {last}")
    pytest.skip("headless chromium unavailable/failed after retries")
