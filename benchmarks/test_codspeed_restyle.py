"""CodSpeed attribution for buffer-less restyle versus full payload refresh.

The browser/GPU lifecycle is covered by the real-Chromium probes. These rows
isolate the Python control-plane win on the issue's representative 200k-point
direct scatter and keep content-hash payload cost visible beside it.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

import xy

N = 200_000


@pytest.fixture(scope="module")
def direct_scatter():
    x = np.linspace(0.0, 1.0, N)
    y = np.sin(x * 40.0)
    return xy.scatter_chart(xy.scatter(x, y, color="#2563eb", size=4)).figure()


def test_restyle_json_only_200k(benchmark, direct_scatter) -> None:
    toggle = [False]

    def restyle() -> dict:
        toggle[0] = not toggle[0]
        return direct_scatter.restyle_message(
            0,
            {"fill": "#dc2626" if toggle[0] else "#2563eb", "opacity": 0.7},
            size=6 if toggle[0] else 4,
        )

    message = benchmark(restyle)
    assert message["type"] == "restyle"
    assert len(json.dumps(message, separators=(",", ":")).encode()) < 160


def test_restyle_full_split_payload_comparator_200k(benchmark, direct_scatter) -> None:
    spec, buffers = benchmark(direct_scatter.build_payload_split)
    assert spec["traces"][0]["tier"] == "direct"
    assert sum(buffer.nbytes for buffer in buffers) >= N * 8
    assert all("hash" in column for column in spec["columns"])
