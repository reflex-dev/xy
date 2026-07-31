"""Negative controls for tolerant visual and semantic gallery gates."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw
from scripts.pyplot_gallery.metrics import (
    compare_images,
    compare_semantics,
    evaluate_dimensions,
    evaluate_visual,
)
from scripts.pyplot_gallery.runtime import _axis_record


def _save_chart(path: Path, *, shift: int = 0, legend: bool = True, colorbar: bool = True) -> None:
    image = Image.new("RGB", (240, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((25 + shift, 15, 190 + shift, 150), outline="black", width=2)
    draw.line(
        (35 + shift, 130, 80 + shift, 95, 120 + shift, 110, 180 + shift, 35), fill="blue", width=4
    )
    if legend:
        draw.rectangle((140 + shift, 25, 185 + shift, 52), fill=(220, 220, 220), outline="black")
        draw.line((145 + shift, 35, 165 + shift, 35), fill="blue", width=3)
    if colorbar:
        draw.rectangle((205, 15, 225, 150), fill=(30, 100, 220), outline="black")
    image.save(path)


def test_identical_renderer_output_passes(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    _save_chart(reference)
    metrics = compare_images(reference, reference)
    assert evaluate_visual(metrics, "filled_vector").decision == "pass"
    assert metrics.normalized_rgb_mae == 0
    assert metrics.dilated_foreground_iou == 1


def test_declared_dark_background_is_used_for_alpha_and_padding(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    image = Image.new("RGBA", (200, 120), (0, 0, 0, 0))
    ImageDraw.Draw(image).line((20, 100, 180, 20), fill=(255, 255, 255, 255), width=3)
    image.save(first)
    image.save(second)
    metrics = compare_images(
        first,
        second,
        reference_background=(8, 12, 20),
        xy_background=(8, 12, 20),
    )
    assert evaluate_visual(metrics, "text_thin_line").decision == "pass"
    assert metrics.normalized_rgb_mae == 0


def test_blank_output_is_rejected(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    blank = tmp_path / "blank.png"
    _save_chart(reference)
    Image.new("RGB", (240, 180), "white").save(blank)
    gate = evaluate_visual(compare_images(reference, blank), "text_thin_line")
    assert gate.decision == "fail"
    assert any("blank" in reason or "foreground-area" in reason for reason in gate.reasons)


def test_blank_dark_candidate_is_rejected_against_declared_dark_background(
    tmp_path: Path,
) -> None:
    background = (8, 12, 20)
    reference = tmp_path / "dark-reference.png"
    blank = tmp_path / "dark-blank.png"
    reference_image = Image.new("RGB", (240, 180), background)
    ImageDraw.Draw(reference_image).line((25, 150, 210, 20), fill="white", width=4)
    reference_image.save(reference)
    Image.new("RGB", (240, 180), background).save(blank)

    gate = evaluate_visual(
        compare_images(
            reference,
            blank,
            reference_background=background,
            xy_background=background,
        ),
        "text_thin_line",
    )

    assert gate.decision == "fail"
    assert any("xy image is blank" in reason for reason in gate.reasons)


def test_filled_bracket_polygon_defect_is_rejected(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    broken = tmp_path / "broken.png"
    first = Image.new("RGB", (240, 180), "white")
    draw = ImageDraw.Draw(first)
    draw.line((50, 40, 40, 40, 40, 140, 50, 140), fill="blue", width=3)
    draw.line((190, 40, 200, 40, 200, 140, 190, 140), fill="blue", width=3)
    first.save(reference)
    second = Image.new("RGB", (240, 180), "white")
    ImageDraw.Draw(second).polygon((20, 20, 220, 90, 20, 160), fill="blue")
    second.save(broken)
    gate = evaluate_visual(compare_images(reference, broken), "text_thin_line")
    assert gate.decision == "fail"


def test_dense_mesh_seams_are_rejected_below_the_global_mae_limit(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    seamed = tmp_path / "seamed.png"
    x = np.linspace(0.0, 1.0, 240, dtype=np.float32)
    y = np.linspace(0.0, 1.0, 180, dtype=np.float32)[:, None]
    smooth = np.empty((180, 240, 3), dtype=np.uint8)
    smooth[:, :, 0] = np.rint(40 + 100 * x).astype(np.uint8)
    smooth[:, :, 1] = np.rint(60 + 90 * y).astype(np.uint8)
    smooth[:, :, 2] = np.rint(180 - 80 * x).astype(np.uint8)
    broken = smooth.copy()
    broken[:, ::4] = np.rint(broken[:, ::4] * 0.72 + 255 * 0.28).astype(np.uint8)
    broken[::4, :] = np.rint(broken[::4, :] * 0.72 + 255 * 0.28).astype(np.uint8)
    Image.fromarray(smooth, mode="RGB").save(reference)
    Image.fromarray(broken, mode="RGB").save(seamed)

    metrics = compare_images(reference, seamed)
    gate = evaluate_visual(metrics, "raster_mesh")

    assert metrics.normalized_rgb_mae < 0.08
    assert metrics.directional_high_frequency_ratio > 1.75
    assert gate.decision == "fail"
    assert any("mesh-seam" in reason for reason in gate.reasons)


def test_missing_legend_and_colorbar_are_rejected(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    missing = tmp_path / "missing.png"
    _save_chart(reference)
    _save_chart(missing, legend=False, colorbar=False)
    gate = evaluate_visual(compare_images(reference, missing), "filled_vector")
    assert gate.decision != "pass"


def test_shifted_layout_is_rejected(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    shifted = tmp_path / "shifted.png"
    _save_chart(reference)
    _save_chart(shifted, shift=38, legend=False)
    gate = evaluate_visual(compare_images(reference, shifted), "filled_vector")
    assert gate.decision != "pass"


def _semantic_axis() -> dict[str, object]:
    return {
        "bounds": [0.1, 0.1, 0.8, 0.8],
        "projection": "rectilinear",
        "xscale": "linear",
        "yscale": "linear",
        "xlim": [0.0, 10.0],
        "ylim": [0.0, 5.0],
        "x_inverted": False,
        "y_inverted": False,
        "x_autoscale": False,
        "y_autoscale": False,
        "title": "Title",
        "xlabel": "x",
        "ylabel": "y",
        "legend_text": ["series"],
        "is_colorbar": True,
        "artist_families": {"line": 1},
    }


def _semantic_axis_3d(*, autoscale: bool = False) -> dict[str, object]:
    axis = _semantic_axis()
    axis.update(
        {
            "projection": "3d",
            "zscale": "linear",
            "zlim": [-2.0, 8.0],
            "z_inverted": False,
            "z_autoscale": autoscale,
            "zlabel": "z",
        }
    )
    return axis


def test_runtime_axis_record_captures_z_semantics_only_for_3d_axes() -> None:
    axis_3d = SimpleNamespace(
        name="3d",
        get_zscale=lambda: "log",
        get_zlim=lambda: (9.0, -1.0),
        zaxis_inverted=lambda: True,
        get_autoscalez_on=lambda: False,
        get_zlabel=lambda: "height",
    )

    record = _axis_record(axis_3d)

    assert record["zscale"] == "log"
    assert record["zlim"] == [9.0, -1.0]
    assert record["z_inverted"] is True
    assert record["z_autoscale"] is False
    assert record["zlabel"] == "height"
    assert not any(key.startswith("z") for key in _axis_record(SimpleNamespace()))


def test_matching_3d_semantics_and_autoscale_tolerance_pass() -> None:
    reference_axis = _semantic_axis_3d(autoscale=True)
    candidate_axis = _semantic_axis_3d(autoscale=True)
    candidate_axis["zlim"] = [-1.5, 8.5]

    assert (
        compare_semantics(
            {"axes": [reference_axis], "figure_text": []},
            {"axes": [candidate_axis], "figure_text": []},
        )
        == []
    )


def test_3d_semantics_reject_z_direction_label_scale_and_explicit_limit_regressions() -> None:
    reference_axis = _semantic_axis_3d()
    candidate_axis = _semantic_axis_3d()
    candidate_axis.update(
        {
            "zscale": "log",
            "zlim": [-2.0, 8.000001],
            "z_inverted": True,
            "zlabel": "depth",
        }
    )

    differences = compare_semantics(
        {"axes": [reference_axis], "figure_text": []},
        {"axes": [candidate_axis], "figure_text": []},
    )

    assert "axes[0] zscale differs" in differences
    assert "axes[0] z_inverted differs" in differences
    assert "axes[0] zlabel differs" in differences
    assert "axes[0] z limits differ" in differences


def test_3d_semantics_reject_z_autoscale_limit_outside_five_percent_span() -> None:
    reference_axis = _semantic_axis_3d(autoscale=True)
    candidate_axis = _semantic_axis_3d(autoscale=True)
    candidate_axis["zlim"] = [-1.49, 8.0]

    differences = compare_semantics(
        {"axes": [reference_axis], "figure_text": []},
        {"axes": [candidate_axis], "figure_text": []},
    )

    assert "axes[0] z limits differ" in differences


def test_semantics_reject_reversed_axis_missing_legend_and_shifted_axes() -> None:
    reference = {"axes": [_semantic_axis()], "figure_text": ["caption"]}
    candidate_axis = _semantic_axis()
    candidate_axis.update(
        {
            "bounds": [0.2, 0.1, 0.8, 0.8],
            "xlim": [10.0, 0.0],
            "x_inverted": True,
            "legend_text": [],
            "is_colorbar": False,
        }
    )
    differences = compare_semantics(
        reference,
        {"axes": [candidate_axis], "figure_text": ["caption"]},
    )
    assert any(
        "bounds" in difference or "rectangle IoU" in difference for difference in differences
    )
    assert any("x_inverted" in difference for difference in differences)
    assert any("x limits" in difference for difference in differences)
    assert any("legend_text" in difference for difference in differences)
    assert any("is_colorbar" in difference for difference in differences)


def test_dimension_policies_are_explicit_and_tolerant() -> None:
    assert evaluate_dimensions((640, 480), (641, 479), policy="explicit").decision == "pass"
    assert evaluate_dimensions((640, 480), (642, 480), policy="explicit").decision == "fail"
    assert evaluate_dimensions((640, 480), (650, 485), policy="default").decision == "pass"
    assert evaluate_dimensions((640, 480), (660, 480), policy="default").decision == "fail"
    assert evaluate_dimensions((500, 100), (520, 103), policy="tight").decision == "pass"
    assert evaluate_dimensions((500, 100), (520, 120), policy="tight").decision == "fail"
