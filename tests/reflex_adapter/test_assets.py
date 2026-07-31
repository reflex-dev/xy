"""Shipped frontend assets: client sourced from the xy install + wrapper contract."""

from __future__ import annotations

import pathlib

import reflex_xy
import xy
from reflex_xy.assets import _client_source, _link_client

ADAPTER_ASSETS = pathlib.Path(reflex_xy.__file__).parent / "assets"


def test_client_is_not_packaged():
    """No second copy of the render client exists to drift: the adapter links
    the installed xy bundle at app compile time."""
    assert not (ADAPTER_ASSETS / "xy_client.js").exists()


def test_client_source_is_the_installed_bundle():
    source = _client_source()
    assert source == pathlib.Path(xy.__file__).resolve().parent / "static" / "index.js"
    text = source.read_text(encoding="utf-8")
    # The installed bundle is minified; its stable public markers are export
    # aliases rather than source-level function/class declarations.
    for marker in ("as renderStandalone", "as decodeFrame", "as ChartView"):
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
    assert "data.version < payloadVersion" in jsx
    assert 'message.type === "append"' in jsx
    # Each subscription is a fresh comparison epoch (a reconnect may land on
    # a worker whose rebuilt cache starts at version 1). Kernel traffic is
    # gated until its authoritative payload arrives.
    reset_epoch = jsx.split("const resetEpoch = () => {", 1)[1].split("};", 1)[0]
    for needle in (
        "clearTimeout(hoverTimer)",
        "clearTimeout(viewTimer)",
        "hoverTimer = null",
        "viewTimer = null",
        "pendingHover = null",
        "pendingView = null",
        "pendingClickInput = null",
        "payloadVersion = null",
        "awaitingPayload = true",
        "clickInputs.clear()",
        "restoreSelectionSeqs.clear()",
        "pendingStatePushes.length = 0",
    ):
        assert needle in reset_epoch
    subscribe = jsx.split("const subscribe = () => {", 1)[1].split("};", 1)[0]
    assert "resetEpoch()" in subscribe
    assert jsx.count("resetEpoch();") == 3  # subscribe, disconnect, cleanup
    assert "awaitingPayload || !socket.connected" in jsx
    assert "awaitingPayload = false" in jsx
    assert 'socket.on("disconnect", onDisconnect)' in jsx
    assert "wireVersion > expected && socket.connected" in jsx
    assert "data.resync === true && socket.connected" in jsx
    # Rejected replies and accepted generation advances both reclaim pending
    # synthetic click/selection bookkeeping.
    assert "discardPendingReply(message)" in jsx
    assert jsx.count("clickInputs.clear()") >= 3
    assert jsx.count("restoreSelectionSeqs.clear()") >= 3
    # Subscription payloads echo a mount id; unaddressed room broadcasts are
    # still accepted, while another mount's direct response is ignored.
    assert "data.mid !== undefined && data.mid !== null && data.mid !== mid" in jsx
    # Versionless programmatic state pushes are not represented by the full
    # payload, so they wait in wire order for either payload-mount path. The
    # exact allow-list plus unaddressed/versionless guards keep stale replies
    # and append deltas out of that queue.
    assert (
        'const DEFERRED_STATE_PUSH_TYPES = new Set(["state_patch", "view_nav", "selection_rows"]);'
    ) in jsx
    assert "data.mid == null" in jsx
    assert "data.version == null" in jsx
    assert "DEFERRED_STATE_PUSH_TYPES.has(message.type)" in jsx
    assert "pendingStatePushes.push({ message, buffers: data.buffers || [] })" in jsx
    assert "if (!deferStatePush(data, message)) discardPendingReply(message)" in jsx
    assert "const queued = pendingStatePushes.splice(0)" in jsx
    assert "for (const { message, buffers } of queued)" in jsx
    assert jsx.count("replayPendingStatePushes();") == 2
    on_payload = jsx.split("const onPayload = (data) => {", 1)[1].split(
        "const onMsg = (data) => {", 1
    )[0]
    in_place_mount, fresh_mount = on_payload.split("reclaimTooltipSlot();", 1)
    assert (
        in_place_mount.index("view?.updatePayload?.")
        < in_place_mount.index("restoreSelectionMask(selectionMaskRequest);")
        < in_place_mount.index("replayPendingStatePushes();")
        < in_place_mount.rindex("return;")
    )
    assert (
        fresh_mount.index("view = new ChartView(")
        < fresh_mount.index("restoreSelectionMask(selectionMaskRequest);")
        < fresh_mount.index("replayPendingStatePushes();")
    )
    # A queued selection replacement must suppress the old selection-mask
    # restore request; its async reply would otherwise arrive after replay and
    # overwrite the newer select/clear/rows push.
    selection_guard = jsx.split(
        "const pendingPushReplacesSelection = () => pendingStatePushes.some", 1
    )[1].split(";", 1)[0]
    assert 'message.type === "selection_rows"' in selection_guard
    assert 'message.type === "state_patch"' in selection_guard
    assert 'hasOwnProperty.call(message.state || {}, "selection")' in selection_guard
    assert "const selectionMaskRequest = pendingPushReplacesSelection()" in jsx
    assert "? null\n        : selectionRequest(selectionToRestore)" in jsx
    # The old view remains mounted while a replacement payload is in flight;
    # it must not arm new semantic view callbacks in that reset epoch.
    dispatch_view = jsx.split("const dispatchView = (m) => {", 1)[1].split("};", 1)[0]
    assert "awaitingPayload" in dispatch_view
    assert "!socket.connected" in dispatch_view
    # the wrapper imports the sibling client copy, not a CDN or npm package
    assert 'from "./xy_client.js"' in jsx
    # static tier: fetch the payload asset, decode the XYBF frame, render
    # kernel-less via the same entry point static HTML exports use
    assert "decodeFrame" in jsx
    assert (
        "renderStandalone(\n"
        "          el, withHoverFlag(fitSpecToElement(frame.message)), frame.buffers[0])"
    ) in jsx
    assert "const controller = new AbortController()" in jsx
    assert "fetch(src, { signal: controller.signal })" in jsx
    assert "controller.abort()" in jsx


def test_wrapper_sizes_static_and_live_charts_to_the_reflex_mount():
    """The inner chart must not overflow dimensions assigned to its component."""
    jsx = (ADAPTER_ASSETS / "XYChart.jsx").read_text(encoding="utf-8")

    assert 'width: "100%"' in jsx
    assert 'height: "100%"' in jsx
    # static tier: fitted spec plus the local hover flag for on_hover
    assert "withHoverFlag(fitSpecToElement(frame.message))" in jsx
    # live tier: eventSpec (fits + enables click/view_change per callbacks)
    # composed with the same hover flag
    assert "const spec = withHoverFlag(eventSpec(data.spec, cbRef.current))" in jsx


def test_wrapper_feeds_hover_payload_to_custom_tooltip_children():
    """xy.tooltip(render=...) children must receive the live §7.1 payload as
    props client-side (Recharts-style cloneElement) — a statically rendered
    slot would show frozen content and defeat the whole contract."""
    jsx = (ADAPTER_ASSETS / "XYChart.jsx").read_text(encoding="utf-8")
    assert "cloneElement(child, {" in jsx
    assert "active: tooltipPayload.active" in jsx
    assert "cursor: tooltipPayload.cursor" in jsx
    assert "points: tooltipPayload.points" in jsx
    # driven by state per hover, not a one-shot render
    assert "setHoverPayload(payload)" in jsx


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
