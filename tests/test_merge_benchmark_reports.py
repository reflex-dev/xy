from __future__ import annotations

import json
from pathlib import Path

from scripts.merge_benchmark_reports import merge


def _partial(path: Path, library: str, *, environment: dict | None = None) -> Path:
    report = {
        "schema_version": 2,
        "environment": environment or {},
        "libraries": [library],
        "sizes": [1_000],
        "budget_s": 45.0,
        "benchmark_categories": [],
        "tracked_categories": [],
        "results": {
            library: [
                {
                    "n": 1_000,
                    "library": library,
                    "status": "unavailable",
                }
            ]
        },
        "ceilings": {library: None},
        "ttfr": False,
    }
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_merge_preserves_expected_library_order(tmp_path: Path) -> None:
    parts = [_partial(tmp_path / "b.json", "b"), _partial(tmp_path / "a.json", "a")]

    merged = merge(parts, ["a", "b"])

    assert list(merged["results"]) == ["a", "b"]
    assert merged["libraries"] == ["a", "b"]
    assert merged["ceilings"] == {"a": None, "b": None}


def test_merge_uses_xy_environment_regardless_of_partial_order(tmp_path: Path) -> None:
    competitor = _partial(
        tmp_path / "competitor.json",
        "matplotlib",
        environment={"python": "competitor-only"},
    )
    native = _partial(
        tmp_path / "native.json",
        "xy",
        environment={"python": "native-xy"},
    )

    merged = merge([competitor, native], ["xy", "matplotlib"])

    assert merged["environment"] == {"python": "native-xy"}


def test_merge_rejects_duplicate_libraries(tmp_path: Path) -> None:
    first = _partial(tmp_path / "first.json", "xy")
    second = _partial(tmp_path / "second.json", "xy")

    try:
        merge([first, second], ["xy"])
    except SystemExit as exc:
        assert "more than one" in str(exc)
    else:  # pragma: no cover - the assertion above is the expected path
        raise AssertionError("duplicate libraries should be rejected")
