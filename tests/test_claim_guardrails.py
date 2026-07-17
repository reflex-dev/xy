from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_claim_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_claim_guardrails.py"
    spec = importlib.util.spec_from_file_location("check_claim_guardrails", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_claim_guardrails = _load_claim_module()


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "doc.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_claim_guardrail_accepts_current_public_docs() -> None:
    findings = check_claim_guardrails.check_claims(check_claim_guardrails._default_paths())

    assert findings == []
    assert check_claim_guardrails.ROOT / "pyproject.toml" in check_claim_guardrails._default_paths()
    assert (
        check_claim_guardrails.ROOT / "examples" / "reflex" / "README.md"
        in check_claim_guardrails._default_paths()
    )
    assert (
        check_claim_guardrails.ROOT / "docs" / "index.md"
        in check_claim_guardrails._default_paths()
    )


def test_claim_guardrail_rejects_broad_fastest_claim(tmp_path: Path) -> None:
    path = _write(tmp_path, "xy is the fastest charting library.\n")

    findings = check_claim_guardrails.check_claims([path])

    assert any("broad superlative" in finding.message for finding in findings)


def test_claim_guardrail_rejects_broad_best_charting_claim(tmp_path: Path) -> None:
    path = _write(tmp_path, "xy is the best Python charting library.\n")

    findings = check_claim_guardrails.check_claims([path])

    assert any("broad superlative" in finding.message for finding in findings)


def test_claim_guardrail_rejects_most_performant_claim(tmp_path: Path) -> None:
    path = _write(tmp_path, "xy is the most performant graphing engine.\n")

    findings = check_claim_guardrails.check_claims([path])

    assert any("broad superlative" in finding.message for finding in findings)


def test_claim_guardrail_rejects_broad_more_performant_claim(tmp_path: Path) -> None:
    path = _write(tmp_path, "xy is more performant than every data library.\n")

    findings = check_claim_guardrails.check_claims([path])

    assert any("broad superlative" in finding.message for finding in findings)


def test_claim_guardrail_rejects_broad_package_metadata_claim(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        'description = "A faster charting engine: native Rust core, binary transport"\n',
    )

    findings = check_claim_guardrails.check_claims([path])

    assert any("broad superlative" in finding.message for finding in findings)


def test_claim_guardrail_rejects_unqualified_plotly_claim(tmp_path: Path) -> None:
    path = _write(tmp_path, "xy is faster than Plotly.\n")

    findings = check_claim_guardrails.check_claims([path])

    assert any("comparative performance" in finding.message for finding in findings)


def test_claim_guardrail_accepts_measured_qualified_plotly_claim(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        (
            "In the smoke benchmark, the native backend is faster than Plotly "
            "for the 100k histogram payload-prep row with TTFR measured.\n"
        ),
    )

    findings = check_claim_guardrails.check_claims([path])

    assert findings == []


def test_claim_guardrail_rejects_unqualified_numeric_multiplier(tmp_path: Path) -> None:
    path = _write(tmp_path, "xy is 10x faster and 5x smaller.\n")

    findings = check_claim_guardrails.check_claims([path])

    assert any("numeric performance multiplier" in finding.message for finding in findings)


def test_claim_guardrail_accepts_measured_numeric_multiplier(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        (
            "Measured in the native backend benchmark with Chrome TTFR.\n\n"
            "| Chart | Workload | Payload-prep vs Plotly | Payload reduction |\n"
            "|---|---:|---:|---:|\n"
            "| Histogram | 100k values / 200 bins | 303x faster | 348x smaller |\n"
        ),
    )

    findings = check_claim_guardrails.check_claims([path])

    assert findings == []


def test_claim_guardrail_accepts_policy_text(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        'Do not write broad claims like "faster than Plotly" without naming chart type.\n',
    )

    findings = check_claim_guardrails.check_claims([path])

    assert findings == []


def test_claim_guardrail_requires_mode_for_large_point_rendering(tmp_path: Path) -> None:
    path = _write(tmp_path, "xy renders 100M points.\n")

    findings = check_claim_guardrails.check_claims([path])

    assert any("large-point rendering" in finding.message for finding in findings)


def test_claim_guardrail_accepts_mode_scoped_large_point_rendering(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "The benchmark measured 100M points in density mode on the native backend.\n",
    )

    findings = check_claim_guardrails.check_claims([path])

    assert findings == []


def test_claim_guardrail_rejects_stale_repo_identity(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "Report issues at https://github.com/Alek99/charts-exp/security/advisories/new\n",
    )

    findings = check_claim_guardrails.check_claims([path])

    assert any("stale repository identity" in finding.message for finding in findings)


def test_claim_guardrail_covers_security_and_contributing_docs() -> None:
    defaults = check_claim_guardrails._default_paths()

    assert check_claim_guardrails.ROOT / "SECURITY.md" in defaults
    assert check_claim_guardrails.ROOT / "CONTRIBUTING.md" in defaults
