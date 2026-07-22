from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "browser_conformance.mjs"

EXPECTED_MATRIX = [
    {
        "id": "direct-linear-scatter-dpr1-reduced",
        "tier": "direct",
        "family": "scatter",
        "dpr": 1,
        "motion": "reduce",
        "axisClasses": ["linear"],
    },
    {
        "id": "decimated-log-line-dpr2-motion",
        "tier": "decimated",
        "family": "line",
        "dpr": 2,
        "motion": "no-preference",
        "axisClasses": ["log"],
    },
    {
        "id": "direct-category-bar-dpr1-motion",
        "tier": "direct",
        "family": "bar",
        "dpr": 1,
        "motion": "no-preference",
        "axisClasses": ["category"],
    },
    {
        "id": "direct-linear-heatmap-dpr2-reduced",
        "tier": "direct",
        "family": "heatmap",
        "dpr": 2,
        "motion": "reduce",
        "axisClasses": ["linear"],
    },
    {
        "id": "direct-named-mesh-dpr1-motion",
        "tier": "direct",
        "family": "mesh",
        "dpr": 1,
        "motion": "no-preference",
        "axisClasses": ["named"],
    },
    {
        "id": "density-linear-scatter-dpr2-reduced",
        "tier": "density",
        "family": "scatter",
        "dpr": 2,
        "motion": "reduce",
        "axisClasses": ["linear"],
    },
]


def run_probe_option(option: str) -> object:
    result = subprocess.run(
        ["node", str(PROBE), option],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def test_browser_conformance_catalog_is_the_reviewed_bounded_matrix() -> None:
    matrix = run_probe_option("--list-cases")

    assert matrix == EXPECTED_MATRIX
    assert {case["tier"] for case in matrix} == {"direct", "decimated", "density"}
    assert {case["family"] for case in matrix} == {
        "scatter",
        "line",
        "bar",
        "heatmap",
        "mesh",
    }
    assert {case["dpr"] for case in matrix} == {1, 2}
    assert {case["motion"] for case in matrix} == {"reduce", "no-preference"}
    assert {axis for case in matrix for axis in case["axisClasses"]} == {
        "linear",
        "log",
        "category",
        "named",
    }


def test_browser_conformance_negative_controls_are_executable() -> None:
    controls = run_probe_option("--self-test")

    assert controls == {
        "catalogGapRejected": True,
        "corruptedSignatureRejected": True,
        "corruptedLayoutRejected": True,
    }


def test_browser_conformance_retains_failure_evidence(tmp_path: Path) -> None:
    evidence_path = tmp_path / "browser-conformance-evidence.json"
    result = subprocess.run(
        [
            "node",
            str(PROBE),
            "--browsers=not-an-engine",
            "--evidence",
            str(evidence_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "failed"
    assert "unknown browser not-an-engine" in evidence["error"]
    assert len(evidence["matrix"]) == len(EXPECTED_MATRIX)


def test_browser_conformance_has_no_skip_path_and_required_engines_fail_loudly() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert ".skip" not in source
    assert "WebGL2 unavailable" in source
    assert "missing selected engines or WebGL2 fail" in source
    assert 'schema: "xy-browser-conformance/v1"' in source
