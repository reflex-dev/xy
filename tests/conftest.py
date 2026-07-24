"""Shared helpers for the browser-probe tests.

Plain functions (pytest puts this directory on ``sys.path``, so probe tests
import them with ``from conftest import run_browser_probe``).
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
from pathlib import Path

import pytest


class _BrowserUnavailable(RuntimeError):
    """The browser binary could not be executed at all — environmental."""


def _dump_dom(chromium: str, page: Path) -> tuple[str | None, str | None]:
    """One headless render pass.

    Returns ``(dom, failure)``; exactly one is set. A ``failure`` string means
    the browser *ran* and did not produce a usable DOM — a crash, an abort, or a
    hang. That is a defect, not an environmental miss, so it must never be
    allowed to degrade into a skip. Only a browser that cannot be spawned at all
    raises `_BrowserUnavailable`.
    """
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
        return None, "chromium timed out after 120s"
    except OSError as exc:  # binary vanished, not executable, exec format error
        raise _BrowserUnavailable(str(exc)) from exc
    if proc.returncode != 0:
        tail = " / ".join((proc.stderr or "").strip().splitlines()[-3:])
        return None, f"chromium exited {proc.returncode}: {tail or '(no stderr)'}"
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

    Headless probes on shared runners have transient warm-up misses (virtual
    time / GL init) that a relaunch clears; a genuine regression fails every
    attempt with a *value* mismatch, which we surface — never retry away.
    """
    page.write_text(document, encoding="utf-8")
    last: str | None = None
    for _ in range(3):
        try:
            dom, failure = _dump_dom(chromium, page)
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
