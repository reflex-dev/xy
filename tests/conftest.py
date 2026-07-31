"""Shared helpers for the browser-probe tests.

Plain functions (pytest puts this directory on ``sys.path``, so probe tests
import them with ``from conftest import run_browser_probe``).
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
from functools import lru_cache
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
_BROWSER_PROBE_RUNNER = Path(__file__).with_name("browser_probe_runner.mjs")


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


class _BrowserUnavailable(RuntimeError):
    """The browser binary could not be executed at all — environmental."""


@lru_cache(maxsize=1)
def _playwright_node() -> tuple[str | None, str | None]:
    """Return the Node driver and a cached local-toolchain error, if any."""

    node = shutil.which("node")
    if node is None:
        return None, "node executable not found"
    try:
        probe = subprocess.run(
            [node, "-e", "require.resolve('playwright')"],
            cwd=_BROWSER_PROBE_RUNNER.parent.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"could not inspect the Playwright driver: {exc}"
    if probe.returncode:
        detail = (probe.stderr or probe.stdout).strip()
        return None, f"Playwright is not installed for {node}: {detail or probe.returncode}"
    return node, None


def _failure_detail(output: str, *, limit: int = 4_000) -> str:
    """Keep the useful beginning and end of a bounded subprocess diagnostic."""

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) > 18:
        lines = [*lines[:12], "...", *lines[-6:]]
    return " / ".join(lines)[:limit]


def _dump_dom(
    chromium: str,
    page: Path,
    result_attribute: str,
) -> tuple[str | None, str | None]:
    """One headless render pass.

    Returns ``(dom, failure)``; exactly one is set. A ``failure`` string means
    the browser *ran* and did not produce a usable DOM — a crash, an abort, or a
    hang. That is a defect, not an environmental miss, so it must never be
    allowed to degrade into a skip. Only a browser that cannot be spawned at all
    raises `_BrowserUnavailable`.
    """
    browser = Path(chromium)
    if not browser.is_file() or not os.access(browser, os.X_OK):
        raise _BrowserUnavailable(f"Chromium executable is missing or not executable: {chromium}")
    node, driver_error = _playwright_node()
    if node is None:
        raise _BrowserUnavailable(driver_error or "Playwright Node driver unavailable")
    try:
        proc = subprocess.run(
            [
                node,
                str(_BROWSER_PROBE_RUNNER),
                chromium,
                page.as_uri(),
                result_attribute,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return None, "Playwright Chromium probe timed out after 30s"
    except OSError as exc:  # binary vanished, not executable, exec format error
        raise _BrowserUnavailable(str(exc)) from exc
    if proc.returncode != 0:
        detail = _failure_detail(proc.stderr or proc.stdout)
        return None, f"chromium exited {proc.returncode}: {detail or '(no diagnostic)'}"
    return proc.stdout, None


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
    ``{result_attribute}-error``. Returns the parsed result payload.

    Every way of *not* getting a result fails the test: a chromium crash or
    non-zero exit, a timeout, a probe error, or a missing result attribute. The
    lone skip left is a browser that cannot be spawned at all, and setting
    ``XY_REQUIRE_BROWSER=1`` turns even that into a failure so CI cannot pass by
    absence.

    Headless probes on shared runners can have transient process/GL startup
    misses that a relaunch clears; a genuine regression fails every attempt
    with a value mismatch, which we surface — never retry away.
    """
    page.write_text(document, encoding="utf-8")
    last: str | None = None
    for _ in range(3):
        try:
            dom, failure = _dump_dom(chromium, page, result_attribute)
        except _BrowserUnavailable as exc:
            if os.environ.get("XY_REQUIRE_BROWSER"):
                pytest.fail(
                    f"{label}: XY_REQUIRE_BROWSER is set but chromium "
                    f"({chromium}) could not be launched: {exc}"
                )
            pytest.skip(f"headless chromium could not be launched: {exc}")
        if failure is not None:
            last = failure
            continue
        assert dom is not None
        error = re.search(rf'{re.escape(result_attribute)}-error="([^"]*)"', dom)
        if error:
            last = f"probe error: {html.unescape(error.group(1))}"
            continue
        match = re.search(rf'{re.escape(result_attribute)}="([^"]*)"', dom)
        if match:
            return json.loads(html.unescape(match.group(1)))
        last = "probe did not finish (no result attribute)"
    pytest.fail(f"{label} could not run after 3 attempts: {last}")
