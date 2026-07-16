"""The static payload tier: Chart -> asset file -> src prop, and inline()."""

from __future__ import annotations

import numpy as np
import pytest
import reflex as rx
import reflex_xy
from reflex_xy.payload_asset import payload_asset
from reflex_xy.tokens import parse_token

import xy
from xy.channel import decode_frame


def make_chart(n: int = 32, seed: float = 1.0):
    xs = np.linspace(0.0, seed, n)
    return xy.line_chart(xy.line(xs, xs * seed), width=400, height=200)


@pytest.fixture
def app_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import reflex_xy.component as component_mod

    monkeypatch.setattr(component_mod, "_component_cls", None)
    return tmp_path


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
    with pytest.raises(TypeError, match=r"figure token .* or a"):
        reflex_xy.chart(42)


def test_inline_token_is_stable_and_pinned(_fresh_registry):
    token = reflex_xy.inline(make_chart(seed=3.0))
    assert token.startswith("xyin-")
    assert parse_token(token) is None  # opaque: no session affinity, shared
    # same content, e.g. another worker importing the module -> same token
    assert reflex_xy.inline(make_chart(seed=3.0)) == token
    assert reflex_xy.inline(make_chart(seed=4.0)) != token

    entry = _fresh_registry.get(token)
    assert entry is not None and entry.pinned
    # pinned entries survive the TTL sweep (no rebuild recipe exists)
    assert _fresh_registry.sweep(now=entry.last_access + 10**9) == []
    assert _fresh_registry.get(token) is not None


def test_unpinned_entries_still_sweep(_fresh_registry):
    token = reflex_xy.register(make_chart())
    entry = _fresh_registry.get(token)
    dropped = _fresh_registry.sweep(now=entry.last_access + 10**9)
    assert dropped == [token]


def test_inline_chart_component_uses_token(app_cwd, _fresh_registry):
    token = reflex_xy.inline(make_chart())
    comp = reflex_xy.chart(token)
    rendered = str(comp)
    assert f'token:"{token}"' in rendered
    assert "src" not in rendered


def test_component_var_still_routes_to_token(app_cwd):
    class SrcTokState(rx.State):
        tok: str = ""

    comp = reflex_xy.chart(SrcTokState.tok)
    assert "token:" in str(comp)
