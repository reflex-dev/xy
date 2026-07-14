from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from scripts.sync_matplotlib_compat import _corpus_calls

import xy.pyplot as plt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load(name: str) -> dict:
    return json.loads((HERE / name).read_text())


def test_compatibility_metadata_covers_the_reviewed_snapshot() -> None:
    snapshot = _load("matplotlib_311_plotting.json")
    metadata = _load("compatibility.json")
    assert metadata["families"].keys() == snapshot["families"].keys()
    assert all(item["level"] in metadata["levels"] for item in metadata["families"].values())


def test_every_supported_plotting_method_has_direct_corpus_coverage() -> None:
    snapshot = _load("matplotlib_311_plotting.json")
    expected = {method for methods in snapshot["families"].values() for method in methods}
    covered = set(_corpus_calls())
    assert expected <= covered, f"missing direct corpus calls: {sorted(expected - covered)}"


def test_corpus_coverage_ignores_calls_on_unrelated_receivers(tmp_path, monkeypatch) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "01_false_credit.py").write_text(
        "import xy.pyplot as plt\nthing.fill([1, 2])\nfig, ax = plt.subplots()\nax.plot([1])\n"
    )
    monkeypatch.setattr("scripts.sync_matplotlib_compat.CORPUS", corpus)
    calls = _corpus_calls()
    assert "plot" in calls
    assert "fill" not in calls


def test_generated_compatibility_documentation_is_fresh() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/sync_matplotlib_compat.py"), "--check"],
        check=True,
    )


def _material_observation(method: str, keyword: str, value: object) -> object:
    _fig, ax = plt.subplots()
    if method == "plot":
        artist = ax.plot([0, 1], [0, 1], **{keyword: value})[0]
        return artist._entry["kwargs"]["width"]
    if method == "scatter":
        artist = ax.scatter([0, 1], [0, 1], **{keyword: value})
        return np.asarray(artist._entry["kwargs"]["size"]).tolist()
    if method == "bar":
        artist = ax.bar([0, 1], [1, 2], **{keyword: value})
        return artist._entry["kwargs"]["width"]
    if method == "hist":
        counts, _edges, _patches = ax.hist([0, 0, 1, 2], bins=2, **{keyword: value})
        return np.asarray(counts).tolist()
    if method == "imshow":
        ax.imshow([[0, 1], [2, 3]], **{keyword: value})
        limits = ax.get_ylim()
        return limits[0] > limits[1]
    raise AssertionError(f"material keyword metadata has no observation adapter for {method}")


def test_material_keyword_metadata_detects_accepted_but_discarded_values() -> None:
    """Changing every declared material value must change observable state."""
    metadata = _load("compatibility.json")
    try:
        for guard in metadata["material_keyword_guards"]:
            first, second = guard["values"]
            before = _material_observation(guard["method"], guard["keyword"], first)
            plt.close("all")
            after = _material_observation(guard["method"], guard["keyword"], second)
            assert before != after, (
                f"{guard['method']} accepted {guard['keyword']}={first!r}/{second!r} "
                "but produced identical observable state"
            )
            plt.close("all")
    finally:
        plt.close("all")
