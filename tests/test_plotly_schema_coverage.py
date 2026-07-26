"""The Plotly coverage number has to be reproducible, and honest about its tail.

§24 asks for compat to be "a measured number". A measured number that anyone
can inflate by widening a rule without noticing is not one, so these tests hold
the properties that make the number mean something: it is regenerated rather
than hand-written, its `unclassified` residue is reported rather than absorbed,
and the classifier stays deterministic.

The suite skips when plotly is absent — it lives in the `bench` extra, and the
committed report is what a reader without it consults.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "plotly_schema_coverage.py"
REPORT = ROOT / "spec" / "api" / "plotly-coverage.md"

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("plotly") is None,
    reason="plotly is in the bench extra; the committed report stands in without it",
)


def _module():
    spec = importlib.util.spec_from_file_location("plotly_schema_coverage", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_committed_report_is_regenerated_not_hand_edited() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_src_companions_and_namespaces_are_out_of_the_denominator() -> None:
    # `marker.colorsrc` is not a second styling decision beside `marker.color`,
    # and a compound node is a namespace rather than a knob. Counting either
    # would pad the denominator in XY's favour.
    module = _module()
    schema, _ = module.load_schema()
    paths = module.attribute_paths(schema)
    assert not any(path.endswith("src") for path in paths)
    assert all(
        schema[path]["superclass"] not in {"CompoundValidator", "CompoundArrayValidator"}
        for path in paths
    )


def test_unclassified_is_reported_rather_than_absorbed() -> None:
    # The residue is large and shrinking it is the work. Folding it into a
    # friendlier bucket would make the table look better and mean less.
    module = _module()
    schema, version = module.load_schema()
    _, summary = module.build_report(schema, version)
    assert summary["unsupported_reasons"]["unclassified"] > 0
    assert "unclassified" in REPORT.read_text(encoding="utf-8")


def test_every_verdict_is_one_of_the_three_section_24_names() -> None:
    module = _module()
    schema, version = module.load_schema()
    _, summary = module.build_report(schema, version)
    assert set(summary["verdicts"]) <= {
        module.SUPPORTED,
        module.MAPPED,
        module.UNSUPPORTED,
    }


def test_classification_is_deterministic_and_first_rule_wins() -> None:
    module = _module()
    # A path matched by a specific rule must not fall through to a general one.
    verdict, surface, _ = module.classify("scatter.marker.symbol")
    assert verdict == module.SUPPORTED and "marker-shape" in surface
    # A trace XY does not implement is unsupported regardless of the attribute.
    verdict, _, reason = module.classify("scatter3d.marker.symbol")
    assert verdict == module.UNSUPPORTED and "no such trace" in reason


def test_the_scoped_number_is_reported_next_to_the_whole_schema_one() -> None:
    # Quoting 3.6% without its scope understates; quoting 10.2% without its
    # scope overstates. The report has to carry both.
    text = REPORT.read_text(encoding="utf-8")
    assert "## Whole schema" in text
    assert "## Scoped to the trace types XY implements" in text
    assert "must be quoted *with* its scope" in text


def test_excluded_subtrees_are_not_stolen_by_the_wildcard_axis_rules() -> None:
    # `fnmatch` lets `*` span dots and the first matching rule wins, so
    # `layout.*axis.showgrid` will happily claim `layout.polar.angularaxis.
    # showgrid` unless the exclusions are ordered ahead of it. That ordering is
    # load-bearing: getting it wrong silently counted 3-D, geo, polar, ternary,
    # and smith axes as supported and overstated the headline number by 127
    # attributes. This pins the ordering, not the prose about it.
    module = _module()
    for path in (
        "layout.scene.xaxis.title.text",
        "layout.scene.yaxis.showgrid",
        "layout.polar.angularaxis.showgrid",
        "layout.polar.radialaxis.range",
        "layout.geo.lataxis.showgrid",
        "layout.ternary.aaxis.ticks",
        "layout.smith.realaxis.linecolor",
    ):
        verdict, _, _ = module.classify(path)
        assert verdict == module.UNSUPPORTED, f"{path} is inside an excluded subtree"

    # The genuine top-level axes still resolve.
    for path in ("layout.xaxis.showgrid", "layout.yaxis.type", "layout.xaxis.range"):
        verdict, surface, _ = module.classify(path)
        assert verdict == module.SUPPORTED and surface, path


def test_the_unsupported_reason_table_accounts_for_every_attribute() -> None:
    # A table whose rows trail off short of the total implies accounting it does
    # not do. The generated report folds the tail into one row and prints the
    # total, so the column sums.
    module = _module()
    schema, version = module.load_schema()
    _, summary = module.build_report(schema, version)
    assert sum(summary["unsupported_reasons"].values()) == summary["verdicts"]["unsupported"]

    text = REPORT.read_text(encoding="utf-8")
    assert "all other reasons" in text
    assert f"**{summary['verdicts']['unsupported']:,}**" in text
