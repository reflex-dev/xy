from __future__ import annotations

import base64
import copy
import importlib.util
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    scripts = ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("visual_baseline", scripts / "visual_baseline.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


visual_baseline = _load_module()


def _semantic() -> dict:
    return {
        "title": [{"axis": "", "side": "", "text": "baseline"}],
        "axis_titles": [],
        "tick_labels": [],
        "legend": [],
        "colorbar": [],
        "slots": {
            "root": [{"x": 0, "y": 0, "w": 900, "h": 430}],
            "canvas": [{"x": 62, "y": 40, "w": 824, "h": 348}],
            "title": [{"x": 0, "y": 6, "w": 900, "h": 18}],
            "legend": [],
            "colorbar": [],
        },
        "font_family": '"XY Visual Baseline"',
        "dpr": 1,
    }


def _solid_png(rgb: tuple[int, int, int]) -> bytes:
    pixels = bytes(rgb) * (visual_baseline.VIEW_W * visual_baseline.VIEW_H)
    return visual_baseline._rgb_png(visual_baseline.VIEW_W, visual_baseline.VIEW_H, pixels)


def _case(png: bytes, semantic: dict | None = None) -> dict:
    raster = visual_baseline._downsample(png)
    return {
        "semantic": semantic or _semantic(),
        "raster": base64.b64encode(raster).decode("ascii"),
        "raster_sha256": visual_baseline._sha256(raster),
    }


def test_committed_manifest_has_pinned_bounded_cases_and_checksums() -> None:
    manifest = visual_baseline._load_manifest(visual_baseline.BASELINE_PATH)

    assert set(manifest["cases"]) == set(visual_baseline.BASELINE_ROUTES)
    assert manifest["pinned"]["browser_engine"] == "chromium"
    assert manifest["pinned"]["playwright"] == "1.61.1"
    assert manifest["pinned"]["viewport"] == [900, 470]
    assert manifest["pinned"]["dpr"] == 1.0
    assert manifest["update"]["review_required"] is True


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("browser_engine", "webkit", "Chromium browser engine"),
        ("browser_version", "149", "exact four-part version"),
    ],
)
def test_manifest_rejects_unpinned_browser_identity(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    manifest = json.loads(visual_baseline.BASELINE_PATH.read_text(encoding="utf-8"))
    manifest["pinned"][field] = value
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(visual_baseline.BaselineError, match=message):
        visual_baseline._load_manifest(path)


def test_corrupt_baseline_raster_is_rejected() -> None:
    manifest = visual_baseline._load_manifest(visual_baseline.BASELINE_PATH)
    case = copy.deepcopy(manifest["cases"][visual_baseline.BASELINE_ROUTES[0]])
    case["raster"] = "not valid base64 !!!"

    with pytest.raises(visual_baseline.BaselineError, match="corrupt baseline raster"):
        visual_baseline._decode_expected(case, "corrupt")


def test_perceptual_oracle_rejects_wrong_color() -> None:
    expected_png = _solid_png((30, 80, 180))
    actual_png = _solid_png((220, 55, 40))

    errors, metrics, _, _ = visual_baseline.compare_case(
        "wrong-color", actual_png, _semantic(), _case(expected_png)
    )

    assert any("perceptual MAE" in error for error in errors)
    assert any("changed-cell fraction" in error for error in errors)
    assert metrics["mean_abs_error"] > visual_baseline.MAX_MEAN_ABS_ERROR


def test_semantic_oracle_rejects_wrong_label_and_geometry() -> None:
    expected = _semantic()
    actual = copy.deepcopy(expected)
    actual["title"][0]["text"] = "corrupt"
    actual["slots"]["canvas"][0]["x"] += 40

    errors = visual_baseline._semantic_errors(expected, actual)

    assert "semantic title differs" in errors
    assert any("canvas[0].x delta" in error for error in errors)


def test_failure_artifacts_include_expected_actual_diff_and_semantics(tmp_path: Path) -> None:
    expected_png = _solid_png((20, 40, 60))
    actual_png = _solid_png((200, 180, 160))
    expected = visual_baseline._downsample(expected_png)
    actual = visual_baseline._downsample(actual_png)

    visual_baseline.write_artifacts(
        tmp_path,
        "failure",
        full_png=actual_png,
        expected=expected,
        actual=actual,
        expected_semantic=_semantic(),
        actual_semantic=_semantic(),
    )

    names = {path.name for path in (tmp_path / "failure").iterdir()}
    assert names == {
        "expected.png",
        "actual.png",
        "actual-full.png",
        "diff.png",
        "expected-semantic.json",
        "actual-semantic.json",
    }
    for name in ("expected.png", "actual.png", "diff.png"):
        width, height, _ = visual_baseline._png_rgba((tmp_path / "failure" / name).read_bytes())
        assert (width, height) == (visual_baseline.SAMPLE_W, visual_baseline.SAMPLE_H)


def test_real_browser_negative_control_matrix_is_complete() -> None:
    assert set(visual_baseline.NEGATIVE_CONTROLS) == {
        "corrupted-data",
        "wrong-color",
        "wrong-label",
        "wrong-geometry",
    }
    source = (ROOT / "scripts" / "visual_baseline.py").read_text(encoding="utf-8")
    assert "if not rejected:" in source
    assert "escaped the visual oracle" in source
    assert "trace.bar.value1" in visual_baseline._CORRUPT_DATA_MUTATION
    assert "updatePayload(spec, bytes)" in visual_baseline._CORRUPT_DATA_MUTATION
    assert "style.opacity" not in visual_baseline._CORRUPT_DATA_MUTATION


def test_baseline_updates_are_forbidden_in_ci(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr(visual_baseline, "_resolve_chromium", lambda explicit: sys.executable)
    monkeypatch.setattr(visual_baseline, "_browser_version", lambda executable: "149.0.7827.55")
    monkeypatch.setattr(visual_baseline, "_font_bytes", lambda: b"font")
    args = SimpleNamespace(
        chromium=sys.executable,
        baseline=tmp_path / "baseline.json",
        update_baselines=True,
        prepared_by="author",
        reason="change",
    )

    with pytest.raises(visual_baseline.BaselineError, match="forbidden in CI"):
        visual_baseline._run(args, tmp_path / "artifacts")


@pytest.mark.parametrize(
    ("prepared_by", "reason"),
    [(None, None), (" ", "change"), ("author", "\t")],
)
def test_baseline_update_requires_provenance(
    monkeypatch, tmp_path: Path, prepared_by: str | None, reason: str | None
) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(visual_baseline, "_resolve_chromium", lambda explicit: sys.executable)
    monkeypatch.setattr(visual_baseline, "_browser_version", lambda executable: "149.0.7827.55")
    monkeypatch.setattr(visual_baseline, "_font_bytes", lambda: b"font")
    args = SimpleNamespace(
        chromium=sys.executable,
        baseline=tmp_path / "baseline.json",
        update_baselines=True,
        prepared_by=prepared_by,
        reason=reason,
    )

    with pytest.raises(visual_baseline.BaselineError, match="requires --prepared-by and --reason"):
        visual_baseline._run(args, tmp_path / "artifacts")


def test_baseline_proposal_writes_review_artifacts(monkeypatch, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_bytes(visual_baseline.BASELINE_PATH.read_bytes())
    white = _solid_png((255, 255, 255))
    black = _solid_png((0, 0, 0))

    @contextmanager
    def fake_pages():
        yield {route: f"file:///{route}.html" for route in visual_baseline.BASELINE_ROUTES}

    class FakeSession:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

    def fake_capture(session, url, name, font, *, mutation=None):
        png = black if mutation else white
        semantic = _semantic()
        return png, semantic, {"loaded": True, "family": "XY Visual Baseline", "dpr": 1}

    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(visual_baseline, "_resolve_chromium", lambda explicit: sys.executable)
    monkeypatch.setattr(visual_baseline, "_browser_version", lambda executable: "149.0.7827.55")
    monkeypatch.setattr(visual_baseline, "_font_bytes", lambda: b"font")
    monkeypatch.setattr(visual_baseline, "_baseline_pages", fake_pages)
    monkeypatch.setattr(visual_baseline, "ChromiumSession", FakeSession)
    monkeypatch.setattr(visual_baseline, "_capture_route", fake_capture)
    monkeypatch.setattr(visual_baseline, "_assert_visual", lambda name, png: None)
    args = SimpleNamespace(
        chromium=sys.executable,
        baseline=baseline,
        update_baselines=True,
        prepared_by="  author  ",
        reason="  intentional change  ",
    )

    rc, evidence = visual_baseline._run(args, tmp_path / "artifacts")

    assert rc == 0
    assert evidence["updated"] is True
    proposal = json.loads(baseline.read_text(encoding="utf-8"))
    assert proposal["update"]["prepared_by"] == "author"
    assert proposal["update"]["reason"] == "intentional change"
    for route in visual_baseline.BASELINE_ROUTES:
        names = {path.name for path in (tmp_path / "artifacts" / route).iterdir()}
        assert names == {
            "expected.png",
            "actual.png",
            "actual-full.png",
            "diff.png",
            "expected-semantic.json",
            "actual-semantic.json",
        }
        width, height, _ = visual_baseline._png_rgba(
            (tmp_path / "artifacts" / route / "actual-full.png").read_bytes()
        )
        assert (width, height) == (visual_baseline.VIEW_W, visual_baseline.VIEW_H)


def test_blank_identity_failure_retains_comparison_artifacts(monkeypatch, tmp_path: Path) -> None:
    white = _solid_png((255, 255, 255))

    @contextmanager
    def fake_pages():
        yield {route: f"file:///{route}.html" for route in visual_baseline.BASELINE_ROUTES}

    class FakeSession:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

    def fake_capture(session, url, name, font, *, mutation=None):
        return white, _semantic(), {"loaded": True, "family": "XY Visual Baseline", "dpr": 1}

    manifest = json.loads(visual_baseline.BASELINE_PATH.read_text(encoding="utf-8"))
    monkeypatch.setattr(visual_baseline, "_resolve_chromium", lambda explicit: sys.executable)
    monkeypatch.setattr(
        visual_baseline,
        "_browser_version",
        lambda executable: manifest["pinned"]["browser_version"],
    )
    monkeypatch.setattr(visual_baseline, "_baseline_pages", fake_pages)
    monkeypatch.setattr(visual_baseline, "ChromiumSession", FakeSession)
    monkeypatch.setattr(visual_baseline, "_capture_route", fake_capture)
    args = SimpleNamespace(
        chromium=sys.executable,
        baseline=visual_baseline.BASELINE_PATH,
        update_baselines=False,
        prepared_by=None,
        reason=None,
    )

    rc, evidence = visual_baseline._run(args, tmp_path / "artifacts")

    assert rc == 1
    assert evidence["status"] == "failed"
    assert any("visual health failure" in failure for failure in evidence["failures"])
    for route in visual_baseline.BASELINE_ROUTES:
        assert (tmp_path / "artifacts" / route / "expected.png").is_file()
        assert (tmp_path / "artifacts" / route / "actual.png").is_file()
        assert (tmp_path / "artifacts" / route / "diff.png").is_file()


def test_unexpected_error_still_writes_failure_evidence(monkeypatch, tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"

    def fail_unexpectedly(args, artifacts):
        raise RuntimeError("simulated CDP response failure")

    monkeypatch.setattr(visual_baseline, "_run", fail_unexpectedly)

    rc = visual_baseline.main(["--evidence", str(evidence_path)])

    assert rc == 1
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "failed"
    assert evidence["error"] == "simulated CDP response failure"


def test_evidence_manifest_is_json_serializable() -> None:
    manifest = json.loads(visual_baseline.BASELINE_PATH.read_text(encoding="utf-8"))
    assert json.loads(json.dumps(manifest))["schema_version"] == visual_baseline.SCHEMA_VERSION
