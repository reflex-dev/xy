"""Shipped frontend assets: client sourced from the xy install + wrapper contract."""

from __future__ import annotations

import pathlib

from scripts.js_exports import missing_esm_exports

import reflex_xy
import xy
from reflex_xy.assets import _client_source, _link_client

ADAPTER_ASSETS = pathlib.Path(reflex_xy.__file__).parent / "assets"
# What XYChart.jsx imports from ./xy_client.js.
WRAPPER_IMPORTS = ("ChartView", "decodeFrame", "renderStandalone")


def test_client_is_not_packaged():
    """No second copy of the render client exists to drift: the adapter links
    the installed xy bundle at app compile time."""
    assert not (ADAPTER_ASSETS / "xy_client.js").exists()


def test_client_source_is_the_installed_bundle():
    source = _client_source()
    assert source == pathlib.Path(xy.__file__).resolve().parent / "static" / "index.js"
    text = source.read_text(encoding="utf-8")
    # The bundle is minified, so verify the ESM export surface rather than
    # implementation spellings the minifier rewrites. Exactly what the wrapper
    # imports from ./xy_client.js — if one disappears, XYChart.jsx breaks.
    missing = missing_esm_exports(text, WRAPPER_IMPORTS)
    assert not missing, f"installed bundle stopped exporting: {missing}"


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
        "pendingSelectionSeqs.clear()",
        "restoreSelectionSeqs.clear()",
        "invalidatedSelectionSeqs.clear()",
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
    assert jsx.count("pendingSelectionSeqs.clear()") >= 3
    assert jsx.count("restoreSelectionSeqs.clear()") >= 3
    assert jsx.count("invalidatedSelectionSeqs.clear()") >= 3
    # Subscription payloads echo a mount id; unaddressed room broadcasts are
    # still accepted, while another mount's direct response is ignored.
    assert "data.mid !== undefined && data.mid !== null && data.mid !== mid" in jsx
    # Programmatic state pushes are not represented by the full payload, so
    # they wait in wire order for either payload-mount path. The exact
    # allow-list plus unaddressed/generation-stamped guards keep replies and
    # append deltas out of that queue, and replay only onto the payload whose
    # FigureEntry generation produced the push.
    assert (
        'const DEFERRED_STATE_PUSH_TYPES = new Set(["state_patch", "view_nav", "selection_rows"]);'
    ) in jsx
    assert "data.mid == null" in jsx
    assert "Number.isInteger(data.version)" in jsx
    assert "DEFERRED_STATE_PUSH_TYPES.has(message.type)" in jsx
    assert "pendingStatePushes.push({ generation, message, buffers: data.buffers || [] })" in jsx
    assert "if (!deferStatePush(data, message)) discardPendingReply(message)" in jsx
    assert "const queued = pendingStatePushes.splice(0)" in jsx
    assert "for (const { generation, message, buffers } of queued)" in jsx
    assert "if (generation === payloadGeneration) dispatchToView(message, buffers)" in jsx
    # Draining one mounted generation drops older writes, replays exact
    # matches, and retains later generations in their original wire order.
    replay_pushes = jsx.split("const replayPendingStatePushes = (payloadGeneration) => {", 1)[
        1
    ].split("};", 1)[0]
    assert (
        replay_pushes.index("if (generation === payloadGeneration)")
        < replay_pushes.index("else if (generation > payloadGeneration)")
        < replay_pushes.index("pendingStatePushes.push({ generation, message, buffers })")
    )
    assert jsx.count("replayPendingStatePushes(nextPayloadVersion);") == 2
    on_payload = jsx.split("const onPayload = (data) => {", 1)[1].split(
        "const onMsg = (data) => {", 1
    )[0]
    # Rebuild recovery may deliver both a room payload and a same-generation
    # addressed reply. Generic duplicates are ignored; addressed px-specific
    # replies remain eligible unless a rows selection is mounted, because that
    # mask cannot be reconstructed after updatePayload rebuilds GPU traces.
    equal_room_guard = "data.version === payloadVersion &&"
    assert equal_room_guard in on_payload
    assert "rowsSelectionMounted" in on_payload
    assert "(data.mid == null || rowsSelectionMounted)" in on_payload
    assert "!awaitingPayload" in on_payload
    assert on_payload.index(equal_room_guard) < on_payload.index("data.version < payloadVersion")
    in_place_mount, fresh_mount = on_payload.split("reclaimTooltipSlot();", 1)
    assert (
        in_place_mount.index("view?.updatePayload?.")
        < in_place_mount.index("awaitingPayload = false;")
        < in_place_mount.index("restoreSelectionMask(selectionMaskRequest);")
        < in_place_mount.index("replayPendingStatePushes(nextPayloadVersion);")
        < in_place_mount.rindex("return;")
    )
    assert (
        fresh_mount.index("view = new ChartView(")
        < fresh_mount.index("awaitingPayload = false;")
        < fresh_mount.index("restoreSelectionMask(selectionMaskRequest);")
        < fresh_mount.index("replayPendingStatePushes(nextPayloadVersion);")
    )
    # A queued selection replacement must suppress the old selection-mask
    # restore request; its async reply would otherwise arrive after replay and
    # overwrite the newer select/clear/rows push.
    selection_guard = jsx.split("const selectionPushReplacesSelection = (message) =>", 1)[1].split(
        ";", 1
    )[0]
    assert 'message.type === "selection_rows"' in selection_guard
    assert 'message.type === "state_patch"' in selection_guard
    assert 'hasOwnProperty.call(message.state || {}, "selection")' in selection_guard
    pending_guard = jsx.split("const pendingPushReplacesSelection = (payloadGeneration) =>", 1)[
        1
    ].split(";", 1)[0]
    assert "generation === payloadGeneration" in pending_guard
    assert "selectionPushReplacesSelection(message)" in pending_guard
    assert "const selectionMaskRequest = pendingPushReplacesSelection(nextPayloadVersion)" in jsx
    assert "? null\n        : selectionRequest(selectionToRestore)" in jsx
    # Once a payload has mounted, a room-wide selection replacement invalidates
    # every older in-flight selection request (user gestures and payload
    # restores). Any eventual addressed reply is consumed before either the
    # Reflex callback or ChartView sees it.
    on_msg = jsx.split("const onMsg = (data) => {", 1)[1].split("const onErr = (data) => {", 1)[0]
    # A state write may overtake the append/full payload that establishes its
    # generation. Queue that write before the ordinary version mismatch path.
    assert (
        on_msg.index("deferredPushGeneration > payloadVersion")
        < on_msg.index("deferStatePush(data, message);")
        < on_msg.index("if (wireVersion !== null && payloadVersion !== null)")
    )
    assert (
        on_msg.index("if (wireVersion !== null && payloadVersion !== null)")
        < on_msg.rindex("invalidateSelectionReplies();")
        < on_msg.index("let clientMessage = message;")
    )
    assert (
        on_msg.index(
            "const selectionWasInvalidated = invalidatedSelectionSeqs.delete(message.seq);"
        )
        < on_msg.index("const selectionWasPending = pendingSelectionSeqs.delete(message.seq);")
        < on_msg.index("if (selectionWasInvalidated || !selectionWasPending) return;")
        < on_msg.index("const isRestore = restoreSelectionSeqs.delete(message.seq);")
        < on_msg.index("cbRef.current.onSelectEnd({")
        < on_msg.index("dispatchToView(clientMessage, data.buffers || []);")
    )
    invalidate_replies = jsx.split("const invalidateSelectionReplies = () => {", 1)[1].split(
        "};", 1
    )[0]
    assert "for (const seq of pendingSelectionSeqs)" in invalidate_replies
    assert "invalidatedSelectionSeqs.add(seq)" in invalidate_replies
    assert "pendingSelectionSeqs.clear()" in invalidate_replies
    assert "restoreSelectionSeqs.clear()" in invalidate_replies
    assert jsx.count("pendingSelectionSeqs.add(") == 2  # user gesture + restore
    # If a state write overtakes its append, apply the data delta first and
    # then replay state for exactly the generation that append established.
    append_advance = on_msg.split(
        'if (wireVersion !== null && message.type === "append" && data.mid == null) {', 1
    )[1]
    assert (
        append_advance.index("payloadVersion = wireVersion;")
        < append_advance.index("dispatchToView(clientMessage, data.buffers || []);")
        < append_advance.index("replayPendingStatePushes(wireVersion);")
        < append_advance.index("return;")
    )
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


def test_same_generation_addressed_payload_invalidates_in_flight_replies():
    """A px-specific payload can change shipped indices without a version bump."""
    jsx = (ADAPTER_ASSETS / "XYChart.jsx").read_text(encoding="utf-8")
    on_payload = jsx.split("const onPayload = (data) => {", 1)[1].split(
        "const onMsg = (data) => {", 1
    )[0]
    on_msg = jsx.split("const onMsg = (data) => {", 1)[1].split("const onErr = (data) => {", 1)[0]
    invalidate = jsx.split("const invalidatePayloadReplies = () => {", 1)[1].split("};", 1)[0]

    for needle in (
        "pendingClickInput = null",
        "clickInputs.clear()",
        "invalidateSelectionReplies()",
    ):
        assert needle in invalidate

    # The duplicate/rows-mask guard runs first. Any same-generation addressed
    # payload that remains eligible invalidates old-payload replies before it
    # snapshots durable state or replaces buffers.
    assert (
        on_payload.index("data.version === payloadVersion")
        < on_payload.index("const sameGenerationAddressedReplacement =")
        < on_payload.index("if (sameGenerationAddressedReplacement) invalidatePayloadReplies();")
        < on_payload.index("const durableState =")
        < on_payload.index("view?.updatePayload?.")
    )
    replacement = on_payload.split("const sameGenerationAddressedReplacement =", 1)[1].split(
        ";", 1
    )[0]
    for needle in (
        "data.mid != null",
        "nextPayloadVersion === payloadVersion",
        "!awaitingPayload",
    ):
        assert needle in replacement

    # Clearing bookkeeping is authoritative: a late same-version reply with
    # an unknown sequence is consumed before any Reflex callback or view
    # dispatch, rather than falling through with empty click metadata.
    assert (
        on_msg.index("const clickWasPending = clickInputs.has(message.seq);")
        < on_msg.index("if (!clickWasPending) return;")
        < on_msg.index("cbRef.current.onPointClick?.(")
    )
    assert (
        on_msg.index(
            "const selectionWasInvalidated = invalidatedSelectionSeqs.delete(message.seq);"
        )
        < on_msg.index("const selectionWasPending = pendingSelectionSeqs.delete(message.seq);")
        < on_msg.index("if (selectionWasInvalidated || !selectionWasPending) return;")
        < on_msg.index("cbRef.current.onSelectEnd({")
        < on_msg.index("dispatchToView(clientMessage, data.buffers || []);")
    )


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
