from __future__ import annotations

import ast
import base64
import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from xy._figure import DECIMATION_THRESHOLD, Figure
from xy.channel import ChannelCallbacks, decode_frame, encode_frame, handle_message

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "spec" / "testing" / "protocol-catalog.json"
CHANNEL_PATH = ROOT / "python" / "xy" / "channel.py"
CLIENT = ROOT / "python" / "xy" / "static" / "index.js"
CATALOG = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
REQUEST_CASES = [
    (request, case_kind, case)
    for request in CATALOG["requests"]
    for case_kind, case in request["cases"].items()
]


def _implemented_request_types(source: str) -> set[str]:
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "handle_message"
    )
    request_types: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Name):
            continue
        if node.left.id != "kind" or len(node.ops) != 1 or len(node.comparators) != 1:
            continue
        comparator = node.comparators[0]
        if isinstance(node.ops[0], ast.Eq) and isinstance(comparator, ast.Constant):
            if isinstance(comparator.value, str):
                request_types.add(comparator.value)
        elif isinstance(node.ops[0], ast.In) and isinstance(comparator, (ast.Set, ast.Tuple)):
            request_types.update(
                value.value
                for value in comparator.elts
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            )
    return request_types


def _catalog_errors(catalog: dict[str, Any], channel_source: str) -> list[str]:
    errors: list[str] = []
    requests = catalog.get("requests")
    if not isinstance(requests, list):
        return ["requests must be a list"]
    names = [request.get("type") for request in requests if isinstance(request, dict)]
    if len(names) != len(set(names)):
        errors.append("request types must be unique")
    implemented = _implemented_request_types(channel_source)
    if set(names) != implemented:
        errors.append(
            f"catalog request types {sorted(names)} do not match implementation {sorted(implemented)}"
        )
    expected_cases = set(catalog.get("request_case_kinds", []))
    for request in requests:
        if not isinstance(request, dict):
            errors.append("request entry must be an object")
            continue
        actual_cases = set(request.get("cases", {}))
        if actual_cases != expected_cases:
            errors.append(
                f"{request.get('type')} cases {sorted(actual_cases)} do not match "
                f"{sorted(expected_cases)}"
            )
    replies = catalog.get("replies", {})
    catalog_reply_types = {
        case["reply"]
        for request in requests
        for case in request.get("cases", {}).values()
        if "reply" in case
    }
    if set(replies) != catalog_reply_types:
        errors.append(
            f"reply catalog {sorted(replies)} does not match generated replies "
            f"{sorted(catalog_reply_types)}"
        )
    return errors


def _figure() -> Figure:
    line = np.arange(DECIMATION_THRESHOLD + 1, dtype=np.float64)
    points = np.arange(100, dtype=np.float64)
    return Figure().line(line, line).scatter(points, points).scatter(points, points, density=True)


def _callbacks(fired: list[str]) -> ChannelCallbacks:
    def record(name: str):
        return lambda _value: fired.append(name)

    return ChannelCallbacks(
        on_hover=record("on_hover"),
        on_click=record("on_click"),
        on_brush=record("on_brush"),
        on_select=record("on_select"),
        on_view_change=record("on_view_change"),
        on_animation_start=record("on_animation_start"),
        on_animation_end=record("on_animation_end"),
    )


def _assert_reply_contract(message: dict[str, Any], buffers: list[bytes] | None) -> None:
    reply = CATALOG["replies"][message["type"]]
    assert set(reply["required"]) <= set(message)
    policy = reply["buffers"]
    if policy == "none":
        assert buffers is None
    elif policy == "nonempty":
        assert buffers
    elif policy == "trace_count":
        assert len(buffers or []) == len(message["traces"])
    else:  # pragma: no cover - catalog schema guard
        raise AssertionError(f"unknown buffer policy {policy!r}")


def test_protocol_catalog_exactly_covers_dispatcher_and_replies() -> None:
    source = CHANNEL_PATH.read_text(encoding="utf-8")
    assert _catalog_errors(CATALOG, source) == []


def test_protocol_catalog_oracle_rejects_missing_branch_and_case() -> None:
    source = CHANNEL_PATH.read_text(encoding="utf-8")
    missing_request = copy.deepcopy(CATALOG)
    missing_request["requests"].pop()
    assert any(
        "do not match implementation" in error for error in _catalog_errors(missing_request, source)
    )

    missing_case = copy.deepcopy(CATALOG)
    missing_case["requests"][0]["cases"].pop("wrong_type")
    assert any("view cases" in error for error in _catalog_errors(missing_case, source))


@pytest.mark.parametrize(
    ("request_entry", "case_kind", "case"),
    REQUEST_CASES,
    ids=[f"{request['type']}-{case_kind}" for request, case_kind, _case in REQUEST_CASES],
)
def test_catalog_generated_request_matrix(
    request_entry: dict[str, Any], case_kind: str, case: dict[str, Any]
) -> None:
    assert isinstance(request_entry["type"], str)
    fired: list[str] = []
    callbacks = _callbacks(fired) if case_kind == "callback" else ChannelCallbacks()

    result = handle_message(_figure(), case["message"], callbacks=callbacks)

    if "reply" in case:
        assert result is not None
        message, buffers = result
        assert message["type"] == case["reply"]
        _assert_reply_contract(message, buffers)
    else:
        assert case["outcome"] in {"drop", "none"}
        assert result is None
    assert fired == case.get("callbacks", [])


@pytest.mark.parametrize("reply_type", sorted(CATALOG["replies"]))
def test_python_reproduces_and_decodes_committed_golden_frames(reply_type: str) -> None:
    golden = CATALOG["replies"][reply_type]["golden"]
    buffers = [base64.b64decode(value) for value in golden["buffers_base64"]]
    frame = base64.b64decode(golden["frame_base64"])

    assert encode_frame(golden["message"], buffers) == frame
    decoded = decode_frame(frame)
    assert decoded.message == golden["message"]
    assert [bytes(buffer) for buffer in decoded.buffers] == buffers
    assert all(buffer.obj is frame for buffer in decoded.buffers)


def test_javascript_decodes_the_same_committed_golden_frames_zero_copy() -> None:
    cases = [
        {
            "type": reply_type,
            "frame": reply["golden"]["frame_base64"],
            "message": reply["golden"]["message"],
            "buffers": reply["golden"]["buffers_base64"],
        }
        for reply_type, reply in sorted(CATALOG["replies"].items())
    ]
    script = f"""
      import {{ decodeFrame }} from {CLIENT.as_uri()!r};
      const cases = {json.dumps(cases)};
      const results = cases.map((item) => {{
        const source = Uint8Array.from(Buffer.from(item.frame, "base64"));
        const decoded = decodeFrame(source.buffer);
        return {{
          type: item.type,
          message: decoded.message,
          buffers: decoded.buffers.map((value) =>
            Buffer.from(value.buffer, value.byteOffset, value.byteLength).toString("base64")),
          aligned: decoded.buffers.every((value) => value.byteOffset % 8 === 0),
          sameBacking: decoded.buffers.every((value) => value.buffer === source.buffer),
        }};
      }});
      process.stdout.write(JSON.stringify(results));
    """

    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    results = json.loads(completed.stdout)

    assert [result["type"] for result in results] == [case["type"] for case in cases]
    for result, case in zip(results, cases, strict=True):
        assert result["message"] == case["message"]
        assert result["buffers"] == case["buffers"]
        assert result["aligned"] is True
        assert result["sameBacking"] is True
