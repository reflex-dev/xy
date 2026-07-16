"""Shipped frontend assets: parity with the canonical bundle + wrapper contract."""

from __future__ import annotations

import pathlib

import reflex_xy

ADAPTER_ASSETS = pathlib.Path(reflex_xy.__file__).parent / "assets"
CANONICAL = pathlib.Path(__file__).resolve().parents[2] / "python" / "xy" / "static"


def test_client_copy_matches_canonical_bundle():
    """xy_client.js is a build artifact: byte-identical to static/index.js.

    On drift: run `node js/build.mjs` and commit both copies.
    """
    adapter = (ADAPTER_ASSETS / "xy_client.js").read_bytes()
    canonical = (CANONICAL / "index.js").read_bytes()
    assert adapter == canonical


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
    assert "renderStandalone(el, frame.message, frame.buffers[0])" in jsx
    assert "fetch(src)" in jsx


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
