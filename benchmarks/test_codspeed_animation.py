"""CodSpeed attribution for declarative animation payload overhead.

Browser frame pacing and GPU allocation lifetime are measured by
``bench_animation.py``. These rows isolate the Python work: stable identity
encoding and the extra binary columns in an otherwise identical payload.

The payload pair rows build ``build_payload_split`` — the widget's production
first-paint transport — so the keyed-minus-plain gap is exactly the encoded
key columns, without the packed layout's join copy (which production never
pays; the packed path stays tracked by test_codspeed_kernels.py's
test_build_payload and export rows). Repointing them from ``build_payload``
created a one-time step change in these two series.
"""

from __future__ import annotations

import numpy as np
import pytest

import xy
from xy import kernels as k
from xy.components import _encode_transition_keys

N = 100_000


@pytest.fixture(scope="session", autouse=True)
def require_native_backend() -> None:
    assert k.BACKEND == "native", (
        "CodSpeed benchmarks must run against the native Rust backend; "
        f"got {k.BACKEND!r}. Build the native core before running them."
    )


@pytest.fixture(scope="session", autouse=True)
def warm_lazy_modules() -> None:
    """Warm lazily-imported submodules before any measured region.

    This module collects first alphabetically, so without its own warmup the
    first payload row would pay lazy submodule import and first-build setup
    for the whole package — the phantom regression documented in
    test_codspeed_kernels.py — instead of tracking its own workload.
    """
    x = np.array([0.0, 1.0, 2.0, 3.0])
    y = np.array([0.0, 1.0, 0.0, 1.0])
    xy.scatter_chart(xy.scatter(x=x, y=y)).figure().build_payload_split()
    xy.scatter_chart(
        xy.scatter(x=x, y=y, key=["a", "b", "c", "d"]),
        xy.animation(match="key", duration=250),
    ).figure().build_payload_split()


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
    spec, buffers = benchmark(plain.build_payload_split)
    assert spec["traces"][0]["n_marks"] == N
    assert "keys" not in spec["traces"][0]
    # Two f32 geometry columns are the floor for the exact scatter tier.
    assert sum(b.nbytes for b in buffers) >= N * 8


def test_animation_keyed_payload_100k(benchmark, payload_figures) -> None:
    _plain, animated = payload_figures
    spec, buffers = benchmark(animated.build_payload_split)
    trace = spec["traces"][0]
    assert trace["n_marks"] == N
    assert set(trace["keys"]) == {"lo", "hi"}
    # Geometry plus the two u32 stable-identity columns the keys add.
    assert sum(b.nbytes for b in buffers) >= N * 16
