"""Shipped frontend assets: client sourced from the xy install + wrapper contract."""

from __future__ import annotations

import pathlib

import reflex_xy
from reflex_xy.assets import _client_source, _link_client

import xy

ADAPTER_ASSETS = pathlib.Path(reflex_xy.__file__).parent / "assets"


def test_client_is_not_packaged():
    """No second copy of the render client exists to drift: the adapter links
    the installed xy bundle at app compile time."""
    assert not (ADAPTER_ASSETS / "xy_client.js").exists()


def test_client_source_is_the_installed_bundle():
    source = _client_source()
    assert source == pathlib.Path(xy.__file__).resolve().parent / "static" / "index.js"
    text = source.read_text(encoding="utf-8")
    for marker in ("function renderStandalone(", "function decodeFrame(", "class ChartView"):
        assert marker in text


def test_link_client_creates_and_repairs(tmp_path):
    asset_root = tmp_path / "assets"
    _link_client(asset_root)
    dst = asset_root / "external" / "reflex_xy" / "assets" / "xy_client.js"
    assert dst.is_symlink()
    assert dst.resolve() == _client_source()

    # idempotent
    _link_client(asset_root)
    assert dst.resolve() == _client_source()

    # a stale link (xy reinstalled elsewhere, venv moved) gets repaired,
    # unlike rx.asset's fixed-location shared files
    dst.unlink()
    imposter = tmp_path / "old_install.js"
    imposter.write_text("stale")
    dst.symlink_to(imposter)
    _link_client(asset_root)
    assert dst.resolve() == _client_source()


def test_wrapper_speaks_the_namespace_protocol():
    """The JSX wrapper and namespace.py must agree on event names and shapes."""
    jsx = (ADAPTER_ASSETS / "XYChart.jsx").read_text(encoding="utf-8")
    # transport identity: same engine.io path as the app socket, /_xy namespace
    assert 'nsUrl.pathname = "/_xy"' in jsx
    assert "path: endpoint.pathname" in jsx
    # client -> server events
    for needle in ('"sub"', '"unsub"', '"msg"'):
        assert f"socket.emit({needle}" in jsx or f"emit({needle}" in jsx
    # server -> client events
    for needle in ('"payload"', '"msg"', '"err"'):
        assert f"socket.on({needle}" in jsx
    # binary columns go straight into typed arrays — never through JSON numbers
    assert "new Uint8Array(b)" in jsx
    # the wrapper imports the sibling client copy, not a CDN or npm package
    assert 'from "./xy_client.js"' in jsx
    # static tier: fetch the payload asset, decode the XYBF frame, render
    # kernel-less via the same entry point static HTML exports use
    assert "decodeFrame" in jsx
    assert (
        "renderStandalone(\n"
        "          el, withHoverFlag(fitSpecToElement(frame.message)), frame.buffers[0])"
    ) in jsx
    assert "fetch(src)" in jsx


def test_wrapper_sizes_static_and_live_charts_to_the_reflex_mount():
    """The inner chart must not overflow dimensions assigned to its component."""
    jsx = (ADAPTER_ASSETS / "XYChart.jsx").read_text(encoding="utf-8")

    assert 'width: "100%"' in jsx
    assert 'height: "100%"' in jsx
    assert "withHoverFlag(fitSpecToElement(frame.message))" in jsx
    assert "withHoverFlag(fitSpecToElement(data.spec))" in jsx


def test_wrapper_discards_tailwind_scan_manifest_before_dom_props():
    """The scan bridge must not become an unknown DOM attribute at runtime."""
    jsx = (ADAPTER_ASSETS / "XYChart.jsx").read_text(encoding="utf-8")

    assert "tailwindClassTokens: _tailwindClassTokens" in jsx
    assert "void _tailwindClassTokens;" in jsx
    assert "...divProps" in jsx


def test_wrapper_mirrors_reflex_connection_options():
    """The shared-manager trick only works if our io() options match reflex's
    connect() (utils/state.js). These names are the coupling surface — if
    reflex renames them, this test is the early warning."""
    jsx = (ADAPTER_ASSETS / "XYChart.jsx").read_text(encoding="utf-8")
    for needle in (
        "getBackendURL(env.EVENT)",
        "transports: [env.TRANSPORT]",
        "protocols: [reflexEnvironment.version]",
        "query: { token: getToken() }",
        "autoUnref: false",
        "reconnection: false",
    ):
        assert needle in jsx, f"wrapper lost reflex connection option: {needle}"
