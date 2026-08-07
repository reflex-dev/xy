"""The v13 capture pair: request out, snapshot back, validated at the door.

Headless like the rest of the widget-boundary tests: the client's half is
covered by the standalone capture smoke; here the kernel's half must send a
well-formed request, settle exactly its own future, validate the reply
through the schema (an out-of-contract capture raises, never becomes IR),
and feed a captured snapshot to the native writers on export.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

import xy
from xy._figure import Figure
from xy.channel import ChannelCallbacks, handle_message
from xy.styling.preflight import StyleCompatibilityError
from xy.styling.resolved import ResolvedStyleSnapshot, SnapshotBuilder, SnapshotEnvironment
from xy.widget import FigureWidget


def _figure() -> Figure:
    return Figure().scatter(np.arange(10.0), np.arange(10.0))


def _widget():
    widget = FigureWidget(_figure())
    sent = []
    widget.send = lambda content, buffers=None: sent.append((content, buffers))
    return widget, sent


def _snapshot_payload(**decl):
    builder = SnapshotBuilder()
    builder.add("tick_label", decl or {"color": "rgb(226, 232, 240)", "font-size": "13px"})
    return builder.build(SnapshotEnvironment(width=640, height=400)).to_payload()


# -- channel dispatch ---------------------------------------------------------


def test_style_snapshot_reply_is_callback_only() -> None:
    fig = _figure()
    seen = []
    callbacks = ChannelCallbacks(on_style_snapshot=seen.append)
    content = {"type": "style_snapshot", "request_id": "r1", "snapshot": {}}
    assert handle_message(fig, content, None, callbacks=callbacks) is None
    assert seen == [content]
    # No listener: drops harmlessly, still no wire reply.
    assert handle_message(fig, content, None) is None


# -- widget round trip --------------------------------------------------------


def test_capture_round_trip_validates_at_the_boundary() -> None:
    widget, sent = _widget()

    async def run():
        task = asyncio.ensure_future(widget.capture_style_snapshot(timeout=5.0))
        await asyncio.sleep(0)
        request = sent[-1][0]
        assert request["type"] == "style_snapshot_request"
        assert request["request_id"]
        widget._on_custom_msg(
            widget,
            {
                "type": "style_snapshot",
                "request_id": request["request_id"],
                "snapshot": _snapshot_payload(),
            },
            None,
        )
        return await task

    snapshot = asyncio.run(run())
    assert isinstance(snapshot, ResolvedStyleSnapshot)
    assert snapshot.instances[0].slot == "tick_label"
    assert widget._pending_style_snapshots == {}


def test_client_capture_errors_raise_instead_of_dangling() -> None:
    widget, sent = _widget()

    async def run():
        task = asyncio.ensure_future(widget.capture_style_snapshot(timeout=5.0))
        await asyncio.sleep(0)
        request = sent[-1][0]
        widget._on_custom_msg(
            widget,
            {
                "type": "style_snapshot",
                "request_id": request["request_id"],
                "error": "capture needs a live window",
            },
            None,
        )
        with pytest.raises(RuntimeError, match="live window"):
            await task

    asyncio.run(run())


def test_out_of_contract_replies_never_become_ir() -> None:
    widget, sent = _widget()

    async def run():
        task = asyncio.ensure_future(widget.capture_style_snapshot(timeout=5.0))
        await asyncio.sleep(0)
        request = sent[-1][0]
        bad = _snapshot_payload()
        bad["version"] = 99
        widget._on_custom_msg(
            widget,
            {"type": "style_snapshot", "request_id": request["request_id"], "snapshot": bad},
            None,
        )
        with pytest.raises(ValueError, match="refusing to guess"):
            await task

    asyncio.run(run())


def test_capture_times_out_loudly() -> None:
    widget, _sent = _widget()

    async def run():
        with pytest.raises(asyncio.TimeoutError):
            await widget.capture_style_snapshot(timeout=0.05)

    asyncio.run(run())
    assert widget._pending_style_snapshots == {}


def test_stale_or_unknown_request_ids_are_ignored() -> None:
    widget, _sent = _widget()
    widget._on_custom_msg(
        widget,
        {"type": "style_snapshot", "request_id": "never-sent", "snapshot": {}},
        None,
    )
    assert widget._pending_style_snapshots == {}


# -- snapshot-fed export ------------------------------------------------------


def _chart(**props):
    return xy.scatter_chart(xy.scatter([1.0, 2.0, 3.0], [2.0, 1.0, 3.0]), **props)


def test_export_reproduces_captured_values_natively() -> None:
    chart = _chart()
    payload = _snapshot_payload()
    svg = chart.to_svg(style_snapshot=payload)
    assert 'fill="rgb(226, 232, 240)"' in svg
    assert 'font-size="13"' in svg
    # Object form is equivalent to payload form.
    from xy.styling.resolved import snapshot_from_payload

    assert chart.to_svg(style_snapshot=snapshot_from_payload(payload)) == svg
    # PNG path renders under the same overlay without error.
    assert chart.to_png(style_snapshot=payload)[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_overlay_is_transient() -> None:
    chart = _chart(styles={"title": {"font-size": 18}})
    fig = chart.figure()
    before_styles = dict(fig.chrome_styles)
    before_style = dict(fig.style)
    fig.to_svg(style_snapshot=_snapshot_payload())
    assert fig.chrome_styles == before_styles
    assert fig.style == before_style


def test_snapshot_is_the_lossless_remedy_strict_recommends() -> None:
    # class_names would drop natively — that is exactly what a captured
    # snapshot carries, so strict passes with one and refuses without one.
    chart = _chart(class_names={"legend": "bg-slate-900"})
    with pytest.raises(StyleCompatibilityError):
        chart.to_png(compatibility="strict")
    data = chart.to_png(compatibility="strict", style_snapshot=_snapshot_payload())
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_snapshot_rejects_the_browser_engine() -> None:
    with pytest.raises(ValueError, match="renders the live cascade"):
        _chart().to_png(engine=xy.Engine.chromium, style_snapshot=_snapshot_payload())
    with pytest.raises(ValueError, match="renders the live cascade"):
        _chart().to_image("png", custom_css=".x{}", style_snapshot=_snapshot_payload())


def test_malformed_snapshots_are_refused_before_any_render() -> None:
    with pytest.raises(ValueError, match="style_snapshot must be"):
        _chart().to_png(style_snapshot=42)
    with pytest.raises(ValueError, match="refusing to guess"):
        _chart().to_png(style_snapshot={"version": 99, "environment": {}})
