"""Windows held-open destination fallback for atomic export writes.

On Windows, `os.replace` is denied (WinError 5) while another handle holds the
destination open — e.g. saving to `NamedTemporaryFile(...).name` inside the
`with` block, or a transient antivirus scan. The writers in `xy.export` must
degrade to an in-place rewrite instead of failing the export. POSIX replaces
open files freely, so these tests simulate the denial by patching
`os.replace` as seen from the export module.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from xy import export


def _deny_replace(monkeypatch):
    """Make every os.replace raise like Windows does for a held-open target."""
    calls = []

    def denied(src, dst, *a, **k):
        calls.append((src, dst))
        raise PermissionError(5, "Access is denied", str(src), 5, str(dst))

    monkeypatch.setattr(export.os, "replace", denied)
    return calls


def _no_sleep(monkeypatch):
    naps = []
    monkeypatch.setattr(export.time, "sleep", naps.append)
    return naps


def test_text_write_falls_back_to_in_place_rewrite(tmp_path, monkeypatch):
    target = tmp_path / "chart.html"
    target.write_text("old", encoding="utf-8")
    _deny_replace(monkeypatch)
    _no_sleep(monkeypatch)

    export._atomic_write_text(target, "<html>new</html>")

    assert target.read_text(encoding="utf-8") == "<html>new</html>"
    assert list(tmp_path.iterdir()) == [target], "temp file must not be left behind"


def test_bytes_write_falls_back_to_in_place_rewrite(tmp_path, monkeypatch):
    target = tmp_path / "chart.png"
    target.write_bytes(b"old")
    _deny_replace(monkeypatch)
    _no_sleep(monkeypatch)

    export._atomic_write_bytes(target, b"\x89PNG new")

    assert target.read_bytes() == b"\x89PNG new"
    assert list(tmp_path.iterdir()) == [target], "temp file must not be left behind"


def test_transient_lock_resolved_by_retry(tmp_path, monkeypatch):
    """Rewrite denied too (scanner holds all access), but the lock clears."""
    target = tmp_path / "out.html"
    target.write_text("old", encoding="utf-8")
    naps = _no_sleep(monkeypatch)

    real_replace = os.replace
    denials = iter(range(2))

    def flaky_replace(src, dst, *a, **k):
        if next(denials, None) is not None:
            raise PermissionError(5, "Access is denied", str(src), 5, str(dst))
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(export.os, "replace", flaky_replace)

    def rewrite_denied(dest: Path) -> None:
        raise PermissionError(5, "Access is denied", str(dest))

    tmp = tmp_path / ".out.html.tmp"
    tmp.write_text("new", encoding="utf-8")
    export._publish_tmp(tmp, target, rewrite_denied)

    assert target.read_text(encoding="utf-8") == "new"
    assert not tmp.exists()
    assert naps == list(export._REPLACE_RETRY_DELAYS_S[:2]), (
        "stopped waiting once replace succeeded"
    )


def test_unrecoverable_lock_raises_actionable_error(tmp_path, monkeypatch):
    target = tmp_path / "out.html"
    target.write_text("old", encoding="utf-8")
    replace_calls = _deny_replace(monkeypatch)
    naps = _no_sleep(monkeypatch)

    def rewrite_denied(dest: Path) -> None:
        raise PermissionError(5, "Access is denied", str(dest))

    tmp = tmp_path / ".out.html.tmp"
    tmp.write_text("new", encoding="utf-8")
    with pytest.raises(PermissionError, match="another process holds it open"):
        export._publish_tmp(tmp, target, rewrite_denied)

    assert target.read_text(encoding="utf-8") == "old", "target left untouched"
    assert len(replace_calls) == 1 + len(export._REPLACE_RETRY_DELAYS_S)
    assert naps == list(export._REPLACE_RETRY_DELAYS_S)


def test_atomic_writer_cleans_temp_when_publish_fails(tmp_path, monkeypatch):
    target = tmp_path / "out.html"
    target.write_text("old", encoding="utf-8")
    _deny_replace(monkeypatch)
    _no_sleep(monkeypatch)

    real_open = Path.open

    def denying_open(self, mode="r", *a, **k):
        if self == target and "w" in mode:
            raise PermissionError(5, "Access is denied", str(self))
        return real_open(self, mode, *a, **k)

    monkeypatch.setattr(Path, "open", denying_open)

    with pytest.raises(PermissionError, match="another process holds it open"):
        export._atomic_write_text(target, "new")

    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [target], "temp file must not be left behind"


def test_to_html_saves_into_held_open_style_target(tmp_path, monkeypatch):
    """End-to-end: the NamedTemporaryFile pattern from the field report."""
    import xy

    _deny_replace(monkeypatch)
    _no_sleep(monkeypatch)

    target = tmp_path / "held.html"
    target.write_text("", encoding="utf-8")
    chart = xy.scatter_chart(xy.scatter([0.0, 1.0, 2.0], [0.0, 1.0, 4.0]))
    returned = chart.to_html(target)

    saved = target.read_text(encoding="utf-8")
    assert saved == returned
    assert "<html" in saved.lower()
    assert list(tmp_path.iterdir()) == [target]
