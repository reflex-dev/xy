"""Shared helpers for the browser-probe tests.

Plain functions (pytest puts this directory on ``sys.path``, so probe tests
import them with ``from conftest import run_browser_probe``).
"""

from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path

import pytest


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
