from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "pan_zoom_matrix.mjs"


def _catalog() -> dict:
    proc = subprocess.run(
        ["node", str(SCRIPT), "--catalog"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


def _valid_evidence(profile: str = "full") -> dict:
    catalog = _catalog()
    selected_ids = catalog["profiles"][profile]["cases"]
    selected = [case for case in catalog["cases"] if case["id"] in selected_ids]
    coverage = {
        field: sorted({value for case in selected for value in case[field]})
        for field in ("actions", "axis_classes", "hosts")
    }
    cases = [
        {
            **case,
            "status": "passed",
            "assertions": {"semantic": ["semantic"], "layout": ["layout"]},
        }
        for case in selected
    ]
    return {
        "schema_version": 1,
        "requirement": "TST-NI-011",
        "profile": profile,
        "status": "passed",
        "catalog": catalog,
        "coverage": coverage,
        "browsers": {
            browser: {"status": "passed", "cases": cases}
            for browser in catalog["profiles"][profile]["browsers"]
        },
    }


def _verify(tmp_path: Path, evidence: dict) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    return subprocess.run(
        ["node", str(SCRIPT), "--verify-evidence", str(path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_catalog_is_bounded_and_covers_the_complete_acceptance_matrix() -> None:
    catalog = _catalog()

    assert catalog["requirement"] == "TST-NI-011"
    assert len(catalog["cases"]) == 7
    assert {action for case in catalog["cases"] for action in case["actions"]} == {
        "drag",
        "wheel",
        "box",
        "toolbar_zoom",
        "reset",
    }
    assert {axis for case in catalog["cases"] for axis in case["axis_classes"]} == {
        "linear",
        "log",
        "reversed",
        "category",
        "dual",
        "named",
    }
    assert {host for case in catalog["cases"] for host in case["hosts"]} == {
        "standalone",
        "reflex-live",
        "reflex-static",
    }
    assert catalog["profiles"]["focused"]["browsers"] == [
        "chromium",
        "firefox",
        "webkit",
    ]


def test_machine_readable_evidence_validator_accepts_complete_evidence(tmp_path: Path) -> None:
    result = _verify(tmp_path, _valid_evidence())

    assert result.returncode == 0, result.stderr
    assert "evidence OK" in result.stdout


def test_machine_readable_evidence_validator_rejects_missing_axis_coverage(
    tmp_path: Path,
) -> None:
    evidence = _valid_evidence()
    evidence["coverage"]["axis_classes"].remove("named")

    result = _verify(tmp_path, evidence)

    assert result.returncode != 0
    assert "axis_classes evidence coverage is incomplete" in result.stderr


def test_machine_readable_evidence_validator_rejects_failed_case(tmp_path: Path) -> None:
    evidence = _valid_evidence()
    evidence["browsers"]["chromium"]["cases"][0]["status"] = "failed"

    result = _verify(tmp_path, evidence)

    assert result.returncode != 0
    assert "did not pass" in result.stderr


def test_probe_drives_real_input_and_real_reflex_hosts() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for token in (
        "page.mouse.down()",
        "page.mouse.wheel",
        "data-xy-modebar-menu-item",
        'for (const id of ["overview", "inline"])',
        "window.__xy_views.get(id)",
        'message.type === "density_view"',
    ):
        assert token in source
