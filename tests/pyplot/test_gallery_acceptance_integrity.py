"""Fail-closed checks for gallery capture provenance and ratchets."""

from __future__ import annotations

import copy
from pathlib import Path

from PIL import Image, ImageDraw
from scripts.pyplot_gallery.integrity import capture_integrity_errors
from scripts.pyplot_gallery.run_gallery import _pair_results, _ratchet_case


def _capture(engine: str, *, background: list[int] | None = None) -> dict[str, object]:
    return {
        "file": "capture-000.png",
        "backend": "module://xy.backends.backend_xy" if engine == "xy" else "Agg",
        "canvas_type": (
            "xy.backends.backend_xy.FigureCanvasXY"
            if engine == "xy"
            else "matplotlib.backends.backend_agg.FigureCanvasAgg"
        ),
        "fallback_used": False if engine == "xy" else None,
        "figure_facecolor_rgba": [1.0, 1.0, 1.0, 1.0],
        "background_rgb": background or [255, 255, 255],
        "semantic": {"axes": [], "figure_text": []},
    }


def _result(engine: str) -> dict[str, object]:
    return {
        "status": "passed",
        "wall_duration_seconds": 0.1,
        "capture_count": 1,
        "captures": [_capture(engine)],
        "capture_errors": [],
        "fallback_used": False if engine == "xy" else None,
        "behavior": {"required": [], "status": "not_required", "errors": []},
    }


def _entry() -> dict[str, object]:
    return {
        "path": "category/example.py",
        "behavior": [],
        "render_class": "text_thin_line",
        "dimension_policy": "default",
    }


def _baseline(*, dimension_gate_passed: bool) -> dict[str, object]:
    engine = {"status": "passed", "duration_seconds": 0.1}
    return {
        "reference": dict(engine),
        "xy": dict(engine),
        "capture_parity": True,
        "dimension_parity": True,
        "dimension_gate_passed": dimension_gate_passed,
        "visual_gate_passed": False,
        "semantic_gate_passed": False,
        "behavior_gate_passed": False,
    }


def test_xy_capture_integrity_requires_exact_canvas_and_explicit_fallback() -> None:
    result = _result("xy")
    assert capture_integrity_errors("xy", result) == []

    wrong_canvas = copy.deepcopy(result)
    wrong_canvas["captures"][0]["canvas_type"] = "matplotlib.backends.backend_agg.FigureCanvasAgg"
    assert any(
        "did not use FigureCanvasXY" in error
        for error in capture_integrity_errors("xy", wrong_canvas)
    )

    wrong_backend = copy.deepcopy(result)
    wrong_backend["captures"][0]["backend"] = "Agg"
    assert any(
        "did not use the XY backend" in error
        for error in capture_integrity_errors("xy", wrong_backend)
    )

    missing_fallback = copy.deepcopy(result)
    del missing_fallback["captures"][0]["fallback_used"]
    missing_fallback.pop("fallback_used")
    errors = capture_integrity_errors("xy", missing_fallback)
    assert any("fallback metadata is missing" in error for error in errors)
    assert any("fallback state is not explicitly false" in error for error in errors)


def test_capture_integrity_requires_backend_canvas_and_background_metadata() -> None:
    result = _result("matplotlib")
    capture = result["captures"][0]
    del capture["backend"]
    del capture["canvas_type"]
    del capture["figure_facecolor_rgba"]
    del capture["background_rgb"]

    errors = capture_integrity_errors("matplotlib", result)

    assert any("backend identity is missing" in error for error in errors)
    assert any("canvas identity is missing" in error for error in errors)
    assert any("figure facecolor is missing" in error for error in errors)
    assert any("declared background is missing" in error for error in errors)


def test_ratchet_rejects_capture_errors_and_uses_tolerant_dimension_gate() -> None:
    results = {"matplotlib": _result("matplotlib"), "xy": _result("xy")}
    results["xy"]["capture_errors"] = ["renderer did not produce capture"]
    comparison = {
        "capture_parity": True,
        "dimension_gate_passed": False,
        "visual_gate_passed": False,
        "semantic_gate_passed": False,
        "behavior_gate_passed": False,
    }

    errors, _warnings = _ratchet_case(
        entry=_entry(),
        baseline=_baseline(dimension_gate_passed=False),
        results=results,
        comparison=comparison,
    )

    assert any("xy has capture errors" in error for error in errors)
    assert not any("canvas-dimension acceptance gate regressed" in error for error in errors)

    errors, _warnings = _ratchet_case(
        entry=_entry(),
        baseline=_baseline(dimension_gate_passed=True),
        results=results,
        comparison=comparison,
    )
    assert any("canvas-dimension acceptance gate regressed" in error for error in errors)


def test_pair_results_passes_each_declared_background_to_metrics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reference_capture = _capture("matplotlib", background=[8, 12, 20])
    xy_capture = _capture("xy", background=[22, 30, 42])
    for engine, capture, background in (
        ("matplotlib", reference_capture, (8, 12, 20)),
        ("xy", xy_capture, (22, 30, 42)),
    ):
        target = tmp_path / "runs" / "category" / "example" / engine
        target.mkdir(parents=True)
        image = Image.new("RGBA", (120, 80), (*background, 0))
        ImageDraw.Draw(image).line((10, 70, 110, 10), fill="white", width=3)
        image.save(target / capture["file"])

    from scripts.pyplot_gallery import run_gallery

    original = run_gallery.compare_images
    received: dict[str, object] = {}

    def spy(reference_path: Path, xy_path: Path, **kwargs):
        received.update(kwargs)
        return original(reference_path, xy_path, **kwargs)

    monkeypatch.setattr(run_gallery, "compare_images", spy)
    comparison = _pair_results(
        entry=_entry(),
        results={
            "matplotlib": {**_result("matplotlib"), "captures": [reference_capture]},
            "xy": {**_result("xy"), "captures": [xy_capture]},
        },
        output_root=tmp_path,
    )

    assert received["reference_background"] == (8, 12, 20)
    assert received["xy_background"] == (22, 30, 42)
    assert comparison["figure_pairs"]


def test_pair_results_fails_visual_gate_when_background_metadata_is_missing(
    tmp_path: Path,
) -> None:
    reference_capture = _capture("matplotlib")
    xy_capture = _capture("xy")
    del xy_capture["background_rgb"]
    for engine, capture in (("matplotlib", reference_capture), ("xy", xy_capture)):
        target = tmp_path / "runs" / "category" / "example" / engine
        target.mkdir(parents=True)
        Image.new("RGB", (120, 80), "white").save(target / capture["file"])

    comparison = _pair_results(
        entry=_entry(),
        results={
            "matplotlib": {**_result("matplotlib"), "captures": [reference_capture]},
            "xy": {**_result("xy"), "captures": [xy_capture]},
        },
        output_root=tmp_path,
    )

    pair = comparison["figure_pairs"][0]
    assert pair["visual_gate"]["decision"] == "fail"
    assert any(
        "background metadata is invalid" in reason for reason in pair["visual_gate"]["reasons"]
    )
    failure = tmp_path / "failures" / "category" / "example" / "figure-000"
    assert sorted(path.name for path in failure.iterdir()) == [
        "difference.png",
        "reference.png",
        "xy.png",
    ]
