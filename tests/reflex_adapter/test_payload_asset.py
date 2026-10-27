"""The static payload tier: Chart -> asset file -> src prop, and inline()."""

from __future__ import annotations

import concurrent.futures
import threading
from pathlib import Path

import numpy as np
import pytest
import reflex as rx

import reflex_xy
import xy
from reflex_xy.payload_asset import payload_asset
from reflex_xy.tokens import parse_token
from xy.channel import decode_frame


def make_chart(n: int = 32, seed: float = 1.0):
    xs = np.linspace(0.0, seed, n)
    return xy.line_chart(xy.line(xs, xs * seed), width=400, height=200)


def test_payload_asset_writes_decodable_frame(app_cwd):
    url = payload_asset(make_chart())
    assert url.startswith("/xy/") and url.endswith(".xyf")
    path = app_cwd / "assets" / url.lstrip("/")
    assert path.exists()
    frame = decode_frame(path.read_bytes())
    spec = frame.message
    assert spec["traces"], "payload spec must carry the traces"
    assert len(frame.buffers) == 1  # one packed blob, renderStandalone's shape
    assert spec.get("buffer_layout") != "split"


def test_payload_asset_is_content_addressed(app_cwd):
    first = payload_asset(make_chart(seed=1.0))
    again = payload_asset(make_chart(seed=1.0))
    other = payload_asset(make_chart(seed=2.0))
    assert first == again  # same data -> same URL (stable across recompiles)
    assert first != other  # changed data -> new URL, never a stale cache hit
    xy_dir = app_cwd / "assets" / "xy"
    assert len(list(xy_dir.glob("*.xyf"))) == 2


def test_payload_asset_write_is_idempotent(app_cwd):
    url = payload_asset(make_chart())
    path = app_cwd / "assets" / url.lstrip("/")
    stamp = path.stat().st_mtime_ns
    assert payload_asset(make_chart()) == url
    assert path.stat().st_mtime_ns == stamp  # existing digest never rewritten


def test_payload_asset_concurrent_writers_use_distinct_temp_files(app_cwd, monkeypatch):
    """Workers compiling the same chart must not rename one shared temp path."""
    original_write_bytes = Path.write_bytes
    both_written = threading.Barrier(2)

    def synchronized_write(path: Path, data: bytes) -> int:
        size = original_write_bytes(path, data)
        if path.name.endswith(".tmp"):
            both_written.wait(timeout=5)
        return size

    monkeypatch.setattr(Path, "write_bytes", synchronized_write)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        urls = list(executor.map(lambda _: payload_asset(make_chart()), range(2)))

    assert urls[0] == urls[1]
    xy_dir = app_cwd / "assets" / "xy"
    assert len(list(xy_dir.glob("*.xyf"))) == 1
    assert not list(xy_dir.glob(".*.tmp"))


def test_payload_asset_skips_write_backend_only(app_cwd, monkeypatch):
    """Prod backend workers re-evaluate stateful pages; they must not need
    (or attempt) to produce frontend files — the URL alone must come out
    identical to the compile process's."""
    monkeypatch.setattr("reflex_xy.payload_asset._should_write", lambda: False)
    url = payload_asset(make_chart())
    assert url.startswith("/xy/")
    assert not (app_cwd / "assets" / "xy").exists()
    monkeypatch.setattr("reflex_xy.payload_asset._should_write", lambda: True)
    assert payload_asset(make_chart()) == url  # deterministic across modes


def test_chart_component_accepts_chart_directly(app_cwd, _fresh_registry):
    comp = reflex_xy.chart(make_chart(), height="220px", id="inline")
    rendered = str(comp)
    assert 'src:"/xy/' in rendered
    assert "token" not in rendered
    # the static tier never touches the registry
    assert len(_fresh_registry) == 0


def test_chart_component_accepts_figure_directly(app_cwd, _fresh_registry):
    comp = reflex_xy.chart(make_chart().figure())
    assert 'src:"/xy/' in str(comp)
    assert len(_fresh_registry) == 0


def test_chart_component_rejects_junk(app_cwd):
    with pytest.raises(TypeError, match=r"figure=.*or a positional"):
        reflex_xy.chart(42)


def test_inline_handle_is_stable_and_pinned(_fresh_registry):
    handle = reflex_xy.inline(make_chart(seed=3.0))
    assert isinstance(handle, reflex_xy.FigureHandle)
    assert handle.token.startswith("xyin-")
    assert parse_token(handle.token) is None  # opaque: no session affinity, shared
    # same content, e.g. another worker importing the module -> same token
    assert reflex_xy.inline(make_chart(seed=3.0)) == handle
    assert reflex_xy.inline(make_chart(seed=4.0)) != handle

    entry = _fresh_registry.get(handle.token)
    assert entry is not None and entry.pinned
    # pinned entries survive the TTL sweep (no rebuild recipe exists)
    assert _fresh_registry.sweep(now=entry.last_access + 10**9) == []
    assert _fresh_registry.get(handle.token) is not None


def test_unpinned_entries_still_sweep(_fresh_registry):
    handle = reflex_xy.register(make_chart())
    entry = _fresh_registry.get(handle.token)
    dropped = _fresh_registry.sweep(now=entry.last_access + 10**9)
    assert dropped == [handle.token]


def test_inline_chart_component_uses_figure_prop(app_cwd, _fresh_registry):
    handle = reflex_xy.inline(make_chart())
    comp = reflex_xy.chart(figure=handle)
    rendered = str(comp)
    assert f'"{handle.token}"' in rendered
    assert "figure" in rendered
    assert "src" not in rendered


def test_positional_handle_routes_to_figure_prop_with_warning(app_cwd, _fresh_registry):
    handle = reflex_xy.inline(make_chart())
    with pytest.warns(DeprecationWarning, match="figure="):
        comp = reflex_xy.chart(handle)
    assert f'"{handle.token}"' in str(comp)


def test_component_str_var_still_routes_to_token(app_cwd):
    class SrcTokState(rx.State):
        tok: str = ""

    with pytest.warns(DeprecationWarning, match="figure="):
        comp = reflex_xy.chart(SrcTokState.tok)
    assert "token:" in str(comp)
