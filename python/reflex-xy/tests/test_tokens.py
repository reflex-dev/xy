"""State-token grammar and property tests for reflex-xy."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from reflex_xy.tokens import build_state_token, parse_token


def test_round_trip():
    token = build_state_token("11111111-2222-4333-8444-555566667777", "root.sub_state", "chart")
    parsed = parse_token(token)
    assert parsed is not None
    assert parsed.client_token == "11111111-2222-4333-8444-555566667777"
    assert parsed.state_full_name == "root.sub_state"
    assert parsed.var_name == "chart"


@pytest.mark.parametrize(
    "bad",
    [
        None,
        123,
        "",
        "xyfig-deadbeef",  # opaque tokens are not state tokens
        "xyv1|short|state|var",  # client token too short
        "xyv1|11111111-2222-4333-8444-555566667777|state",  # missing var
        "xyv1|11111111-2222-4333-8444-555566667777|sta te|var",  # bad state chars
        "xyv1|11111111-2222-4333-8444-555566667777|state|1var",  # bad identifier
        "xyv2|11111111-2222-4333-8444-555566667777|state|var",  # unknown version
    ],
)
def test_parse_fails_closed(bad):
    assert parse_token(bad) is None


def test_build_rejects_separator_smuggling():
    with pytest.raises(ValueError):
        build_state_token("evil|token", "state", "var")
    with pytest.raises(ValueError):
        build_state_token("11111111-2222-4333-8444-555566667777", "state", "var|x")


@given(st.text(max_size=64))
def test_parse_never_raises(garbage):
    parse_token(garbage)  # any outcome but an exception
