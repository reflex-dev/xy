from __future__ import annotations

import subprocess

from conftest import _failure_detail, _playwright_node


def test_browser_probe_driver_caches_missing_playwright(monkeypatch) -> None:
    calls = 0

    monkeypatch.setattr("conftest.shutil.which", lambda name: "/usr/bin/node")

    def missing(*args, **kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(args[0], 1, "", "module not found")

    monkeypatch.setattr("conftest.subprocess.run", missing)
    _playwright_node.cache_clear()
    try:
        assert _playwright_node() == (
            None,
            "Playwright is not installed for /usr/bin/node: module not found",
        )
        assert _playwright_node() == (
            None,
            "Playwright is not installed for /usr/bin/node: module not found",
        )
        assert calls == 1
    finally:
        _playwright_node.cache_clear()


def test_browser_probe_failure_detail_keeps_root_cause_and_tail() -> None:
    lines = ["browserType.launch: sandbox denied", *(f"frame {i}" for i in range(30)), "exit 1"]

    detail = _failure_detail("\n".join(lines))

    assert "browserType.launch: sandbox denied" in detail
    assert "frame 29" in detail
    assert "exit 1" in detail
