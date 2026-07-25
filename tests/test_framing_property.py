from __future__ import annotations

import pytest

from xy.channel import decode_frame, encode_frame

hypothesis = pytest.importorskip("hypothesis")
st = pytest.importorskip("hypothesis.strategies")
given = hypothesis.given
settings = hypothesis.settings


JSON_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False, width=64),
    st.text(max_size=32),
)
JSON_VALUES = st.recursive(
    JSON_SCALARS,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=16), children, max_size=5),
    ),
    max_leaves=20,
)


@settings(max_examples=100, deadline=None)
@given(
    message=st.dictionaries(st.text(max_size=16), JSON_VALUES, max_size=8),
    buffers=st.lists(st.binary(max_size=256), max_size=8),
)
def test_python_frame_round_trip_is_zero_copy(message: dict, buffers: list[bytes]) -> None:
    body = encode_frame(message, buffers)

    decoded = decode_frame(body)

    assert decoded.message == message
    assert [bytes(buffer) for buffer in decoded.buffers] == buffers
    assert all(buffer.obj is body for buffer in decoded.buffers)
