from __future__ import annotations

from dataclasses import replace

import pytest
from scripts import chart_kind_matrix


def test_catalog_exactly_covers_shipped_mark_registry() -> None:
    registry = chart_kind_matrix.shipped_registry()
    chart_kind_matrix.validate_catalog(chart_kind_matrix.CASES, registry)
    assert len(registry) == 18


@pytest.mark.parametrize("case", chart_kind_matrix.CASES, ids=lambda case: case.name)
def test_every_catalog_case_has_nonempty_tiered_payload(case: chart_kind_matrix.Case) -> None:
    _, spec, payload = chart_kind_matrix.build_case(case)
    assert payload
    assert tuple(trace["kind"] for trace in spec["traces"]) == case.expected_kinds
    assert all(trace["tier"] in {"direct", "decimated", "density"} for trace in spec["traces"])
    assert all(trace["n_points"] > 0 for trace in spec["traces"])


def test_catalog_rejects_missing_registry_kind() -> None:
    registry = chart_kind_matrix.shipped_registry()
    with pytest.raises(AssertionError, match=r"catalog mismatch.*missing"):
        chart_kind_matrix.validate_catalog(chart_kind_matrix.CASES[:-1], registry)


def test_payload_oracle_rejects_wrong_expected_kind() -> None:
    broken = replace(chart_kind_matrix.CASES[0], expected_kinds=("line",))
    with pytest.raises(AssertionError, match="payload kinds"):
        chart_kind_matrix.build_case(broken)


def test_pixel_oracle_rejects_blank_render() -> None:
    with pytest.raises(AssertionError, match="blank/flat"):
        chart_kind_matrix.require_nonblank_pixels("mutant", 0)
