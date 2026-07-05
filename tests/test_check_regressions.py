from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_regression_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_regressions.py"
    spec = importlib.util.spec_from_file_location("check_regressions", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_regressions = _load_regression_module()


def test_flatten_accepts_schema_v2_scatter_report() -> None:
    scatter = {
        "schema_version": 2,
        "rows": [
            {
                "n": 1_000_000,
                "tier": "density",
                "wire_bytes": 786_432,
                "wire_bytes_per_point": 0.786432,
            }
        ],
    }
    kernel = {
        "rows": [
            {
                "n": 1_000_000,
                "encode_mpts_s": 1200.0,
                "zoom_redecimate_ms": 0.5,
            }
        ]
    }

    flat = check_regressions.flatten(scatter, kernel)

    assert flat["scatter.tier.1000000"] == "density"
    assert flat["scatter.wire_bytes.1000000"] == 786_432
    assert flat["scatter.wire_bytes_per_point.1000000"] == 0.7864
    assert flat["kernel.encode_mpts_s.1000000"] == 1200.0
    assert flat["kernel.zoom_redecimate_ms.1000000"] == 0.5


def test_flatten_keeps_legacy_scatter_list_compatibility() -> None:
    scatter = [
        {
            "n": 100_000,
            "tier": "direct",
            "wire_bytes": 800_000,
            "wire_bytes_per_point": 8.0,
        }
    ]

    flat = check_regressions.flatten(scatter, None)

    assert flat == {
        "scatter.tier.100000": "direct",
        "scatter.wire_bytes.100000": 800_000,
        "scatter.wire_bytes_per_point.100000": 8.0,
    }
