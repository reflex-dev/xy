"""CodSpeed attribution for declarative animation payload overhead.

Browser frame pacing and GPU allocation lifetime are measured by
``bench_animation.py``. These rows isolate the Python work: stable identity
encoding and the extra binary columns in an otherwise identical payload.
"""

from __future__ import annotations

import numpy as np
import pytest

import xy
from xy.components import _encode_transition_keys

N = 100_000


@pytest.fixture(scope="module")
def animation_data() -> tuple[np.ndarray, np.ndarray, list[str]]:
    x = np.arange(N, dtype=np.float64)
    y = np.sin(x * 0.002).astype(np.float64, copy=False)
    keys = [f"row-{index}" for index in range(N)]
    return x, y, keys


@pytest.fixture(scope="module")
def payload_figures(animation_data):
    x, y, keys = animation_data
    plain = xy.scatter_chart(xy.scatter(x=x, y=y)).figure()
    animated = xy.scatter_chart(
        xy.scatter(x=x, y=y, key=keys),
        xy.animation(match="key", duration=250),
    ).figure()
    return plain, animated


def test_animation_encode_100k_stable_keys(benchmark, animation_data) -> None:
    _x, _y, keys = animation_data
    encoded = benchmark(_encode_transition_keys, keys, N, "benchmark key")
    assert encoded.shape == (N, 2)
    assert encoded.dtype == np.uint32


def test_animation_plain_payload_100k(benchmark, payload_figures) -> None:
    plain, _animated = payload_figures
    spec, blob = benchmark(plain.build_payload)
    assert spec["traces"][0]["n_marks"] == N
    assert "keys" not in spec["traces"][0]
    assert blob


def test_animation_keyed_payload_100k(benchmark, payload_figures) -> None:
    _plain, animated = payload_figures
    spec, blob = benchmark(animated.build_payload)
    trace = spec["traces"][0]
    assert trace["n_marks"] == N
    assert set(trace["keys"]) == {"lo", "hi"}
    assert len(blob) > N * 8
