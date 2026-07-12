from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


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


def test_flatten_accepts_transport_report() -> None:
    transport = {
        "envelopes": [
            {
                "mode": "aligned-binary-diagnostic",
                "wire_bytes": 1024,
                "gzip_bytes": 512,
                "wire_to_payload_ratio": 1.01,
                "encode_p50_ms": 0.1,
            }
        ],
        "append_diagnostics": {
            "widget_binary_transmissions": 2,
            "widget_binary_bytes": 2048,
            "single_trace_append_wire_bytes": 1024,
            "two_trace_append_wire_bytes": 2048,
            "extra_unaffected_trace_wire_bytes": 1024,
        },
    }

    flat = check_regressions.flatten(None, None, transport)

    assert flat == {
        "transport.aligned-binary-diagnostic.wire_bytes": 1024,
        "transport.aligned-binary-diagnostic.gzip_bytes": 512,
        "transport.aligned-binary-diagnostic.wire_to_payload_ratio": 1.01,
        "transport.append.widget_binary_transmissions": 2,
        "transport.append.widget_binary_bytes": 2048,
        "transport.append.single_trace_append_wire_bytes": 1024,
        "transport.append.two_trace_append_wire_bytes": 2048,
        "transport.append.extra_unaffected_trace_wire_bytes": 1024,
    }


def test_transport_bytes_and_transmissions_are_hard_max_gates() -> None:
    assert check_regressions.policy("transport.raw.gzip_bytes") == ("max", "hard", 0.02)
    assert check_regressions.policy("transport.append.widget_binary_bytes") == (
        "max",
        "hard",
        0.02,
    )
    assert check_regressions.policy("transport.append.widget_binary_transmissions") == (
        "max",
        "hard",
        0.0,
    )


def test_missing_baseline_metric_is_a_hard_failure(tmp_path: Path, monkeypatch) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "metrics": {
                    "scatter.tier.100000": "direct",
                    "scatter.wire_bytes.100000": 800000,
                    "scatter.wire_bytes.1000000": 850000,
                }
            }
        ),
        encoding="utf-8",
    )
    scatter = tmp_path / "scatter.json"
    scatter.write_text(
        json.dumps(
            {
                "measurement_scope": "production-figure-payload",
                "rows": [
                    {
                        "n": 100000,
                        "tier": "direct",
                        "wire_bytes": 800000,
                        "wire_bytes_per_point": 8.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_regressions, "BASELINE", baseline)
    monkeypatch.setattr(sys, "argv", ["check_regressions.py", "--scatter", str(scatter)])

    with pytest.raises(SystemExit):
        check_regressions.main()


def test_catastrophic_timing_regression_is_a_hard_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"metrics": {"kernel.encode_mpts_s.1000000": 1_000.0}}),
        encoding="utf-8",
    )
    kernel = tmp_path / "kernel.json"
    kernel.write_text(
        json.dumps({"rows": [{"n": 1_000_000, "encode_mpts_s": 100.0}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_regressions, "BASELINE", baseline)
    monkeypatch.setattr(sys, "argv", ["check_regressions.py", "--kernel", str(kernel)])

    with pytest.raises(SystemExit):
        check_regressions.main()


def test_large_but_noncatastrophic_timing_regression_stays_advisory(
    tmp_path: Path,
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"metrics": {"kernel.encode_mpts_s.1000000": 1_000.0}}),
        encoding="utf-8",
    )
    kernel = tmp_path / "kernel.json"
    kernel.write_text(
        json.dumps({"rows": [{"n": 1_000_000, "encode_mpts_s": 400.0}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_regressions, "BASELINE", baseline)
    monkeypatch.setattr(sys, "argv", ["check_regressions.py", "--kernel", str(kernel)])

    check_regressions.main()

    assert "advisory timing regression" in capsys.readouterr().out


def test_shared_runner_sized_timing_regression_stays_advisory(
    tmp_path: Path,
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"metrics": {"kernel.zone_maps_mpts_s.10000000": 1_310.92}}),
        encoding="utf-8",
    )
    kernel = tmp_path / "kernel.json"
    kernel.write_text(
        json.dumps({"rows": [{"n": 10_000_000, "zone_maps_mpts_s": 244.36}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_regressions, "BASELINE", baseline)
    monkeypatch.setattr(sys, "argv", ["check_regressions.py", "--kernel", str(kernel)])

    check_regressions.main()

    assert "advisory timing regression" in capsys.readouterr().out
