"""Renderer-tolerant visual and semantic gallery comparisons."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

IOU_THRESHOLDS = {
    "text_thin_line": 0.55,
    "filled_vector": 0.70,
    "raster_mesh": 0.80,
}


@dataclass(frozen=True)
class VisualMetrics:
    """Full-canvas perceptual measurements after renderer-noise normalization."""

    reference_dimensions: tuple[int, int]
    xy_dimensions: tuple[int, int]
    normalized_dimensions: tuple[int, int]
    normalized_rgb_mae: float
    reference_foreground_fraction: float
    xy_foreground_fraction: float
    foreground_area_ratio: float
    dilated_foreground_iou: float
    directional_high_frequency_ratio: float


@dataclass(frozen=True)
class GateResult:
    """A pass, review, or failure and the exact reasons for it."""

    decision: str
    reasons: tuple[str, ...]


def _rgb_on_background(
    path: Path,
    background: tuple[int, int, int],
) -> Image.Image:
    with Image.open(path) as opened:
        rgba = opened.convert("RGBA")
    canvas = Image.new("RGBA", rgba.size, (*background, 255))
    return Image.alpha_composite(canvas, rgba).convert("RGB")


def _normalized_pair(
    reference: Image.Image,
    candidate: Image.Image,
    *,
    reference_background: tuple[int, int, int],
    candidate_background: tuple[int, int, int],
    max_side: int,
) -> tuple[Image.Image, Image.Image]:
    width = max(reference.width, candidate.width)
    height = max(reference.height, candidate.height)
    reference_canvas = Image.new("RGB", (width, height), reference_background)
    candidate_canvas = Image.new("RGB", (width, height), candidate_background)
    reference_canvas.paste(reference, (0, 0))
    candidate_canvas.paste(candidate, (0, 0))

    reference_canvas = reference_canvas.filter(ImageFilter.GaussianBlur(radius=1.5))
    candidate_canvas = candidate_canvas.filter(ImageFilter.GaussianBlur(radius=1.5))
    scale = min(1.0, max_side / max(width, height))
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return (
        reference_canvas.resize(size, Image.Resampling.LANCZOS),
        candidate_canvas.resize(size, Image.Resampling.LANCZOS),
    )


def _foreground_mask(image: np.ndarray, background: tuple[int, int, int]) -> np.ndarray:
    background_array = np.asarray(background, dtype=np.int16)
    delta = np.max(np.abs(image.astype(np.int16) - background_array), axis=2)
    return delta > 12


def _dilate(mask: np.ndarray) -> np.ndarray:
    image = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    return np.asarray(image.filter(ImageFilter.MaxFilter(size=11))) > 0


def _directional_total_variation(image: Image.Image) -> tuple[float, float]:
    """Measure full-resolution horizontal/vertical high-frequency energy."""
    rgb = np.asarray(image, dtype=np.float32) / 255.0
    luminance = rgb @ np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32)
    horizontal = float(np.mean(np.abs(np.diff(luminance, axis=1))))
    vertical = float(np.mean(np.abs(np.diff(luminance, axis=0))))
    return horizontal, vertical


def compare_images(
    reference_path: Path,
    xy_path: Path,
    *,
    reference_background: tuple[int, int, int] = (255, 255, 255),
    xy_background: tuple[int, int, int] = (255, 255, 255),
    max_side: int = 256,
) -> VisualMetrics:
    """Compare complete canvases without requiring exact renderer pixels."""

    reference = _rgb_on_background(reference_path, reference_background)
    xy_image = _rgb_on_background(xy_path, xy_background)
    reference_variation = _directional_total_variation(reference)
    xy_variation = _directional_total_variation(xy_image)

    def variation_ratio(candidate: float, expected: float) -> float:
        if expected <= 1e-9:
            return 1.0 if candidate <= 1e-9 else 1_000_000.0
        return min(candidate / expected, 1_000_000.0)

    high_frequency_ratio = max(
        variation_ratio(xy_variation[0], reference_variation[0]),
        variation_ratio(xy_variation[1], reference_variation[1]),
    )
    normalized_reference, normalized_xy = _normalized_pair(
        reference,
        xy_image,
        reference_background=reference_background,
        candidate_background=xy_background,
        max_side=max_side,
    )
    reference_array = np.asarray(normalized_reference)
    xy_array = np.asarray(normalized_xy)
    mae = float(
        np.mean(np.abs(reference_array.astype(np.float64) - xy_array.astype(np.float64)) / 255.0)
    )

    reference_mask = _foreground_mask(reference_array, reference_background)
    xy_mask = _foreground_mask(xy_array, xy_background)
    reference_fraction = float(np.mean(reference_mask))
    xy_fraction = float(np.mean(xy_mask))
    ratio = (
        xy_fraction / reference_fraction
        if reference_fraction
        else (1.0 if not xy_fraction else math.inf)
    )
    dilated_reference = _dilate(reference_mask)
    dilated_xy = _dilate(xy_mask)
    union = np.logical_or(dilated_reference, dilated_xy)
    iou = (
        float(np.logical_and(dilated_reference, dilated_xy).sum() / union.sum())
        if union.any()
        else 1.0
    )
    return VisualMetrics(
        reference_dimensions=reference.size,
        xy_dimensions=xy_image.size,
        normalized_dimensions=normalized_reference.size,
        normalized_rgb_mae=mae,
        reference_foreground_fraction=reference_fraction,
        xy_foreground_fraction=xy_fraction,
        foreground_area_ratio=ratio,
        dilated_foreground_iou=iou,
        directional_high_frequency_ratio=high_frequency_ratio,
    )


def evaluate_visual(metrics: VisualMetrics, render_class: str) -> GateResult:
    """Apply the gallery's tolerant visual acceptance and review bands."""

    if render_class not in IOU_THRESHOLDS:
        raise ValueError(f"unknown render class: {render_class}")
    reasons: list[str] = []
    review = False
    if metrics.reference_foreground_fraction == 0.0:
        reasons.append("reference image is blank")
    if metrics.xy_foreground_fraction == 0.0:
        reasons.append("xy image is blank")
    if metrics.normalized_rgb_mae > 0.12:
        reasons.append(f"normalized RGB MAE {metrics.normalized_rgb_mae:.4f} exceeds 0.12")
    elif metrics.normalized_rgb_mae > 0.08:
        review = True
        reasons.append(f"normalized RGB MAE {metrics.normalized_rgb_mae:.4f} requires review")
    if not 0.67 <= metrics.foreground_area_ratio <= 1.50:
        reasons.append(
            f"foreground-area ratio {metrics.foreground_area_ratio:.4f} is outside [0.67, 1.50]"
        )
    if metrics.directional_high_frequency_ratio > 1.75 and metrics.normalized_rgb_mae > 0.015:
        reasons.append(
            "directional high-frequency ratio "
            f"{metrics.directional_high_frequency_ratio:.4f} exceeds the 1.75 mesh-seam limit"
        )

    threshold = IOU_THRESHOLDS[render_class]
    if metrics.dilated_foreground_iou < threshold - 0.10:
        reasons.append(
            f"dilated foreground IoU {metrics.dilated_foreground_iou:.4f} "
            f"is below {threshold - 0.10:.2f}"
        )
    elif metrics.dilated_foreground_iou < threshold:
        review = True
        reasons.append(
            f"dilated foreground IoU {metrics.dilated_foreground_iou:.4f} "
            f"requires review against {threshold:.2f}"
        )

    hard_fail = any(
        marker in reason
        for reason in reasons
        for marker in ("blank", "exceeds", "outside", "is below")
    )
    return GateResult(
        decision="fail" if hard_fail else ("review" if review else "pass"),
        reasons=tuple(reasons),
    )


def evaluate_dimensions(
    reference: tuple[int, int],
    candidate: tuple[int, int],
    *,
    policy: str,
) -> GateResult:
    """Apply explicit/default/tight canvas-dimension rules."""

    rw, rh = reference
    cw, ch = candidate
    reasons: list[str] = []
    if policy == "explicit":
        if abs(rw - cw) > 1 or abs(rh - ch) > 1:
            reasons.append(f"explicit canvas differs: reference={reference}, xy={candidate}")
    elif policy == "default":
        if abs(rw - cw) / max(rw, 1) > 0.02 or abs(rh - ch) / max(rh, 1) > 0.02:
            reasons.append(f"default canvas differs by more than 2%: {reference} vs {candidate}")
    elif policy == "tight":
        if abs(rw - cw) / max(rw, 1) > 0.05 or abs(rh - ch) / max(rh, 1) > 0.05:
            reasons.append(f"tight canvas differs by more than 5%: {reference} vs {candidate}")
        reference_aspect = rw / max(rh, 1)
        candidate_aspect = cw / max(ch, 1)
        if abs(reference_aspect - candidate_aspect) / max(reference_aspect, 1e-12) > 0.03:
            reasons.append("tight canvas aspect ratio differs by more than 3%")
    else:
        raise ValueError(f"unknown dimension policy: {policy}")
    return GateResult(decision="fail" if reasons else "pass", reasons=tuple(reasons))


def _rect_iou(first: Iterable[float], second: Iterable[float]) -> float:
    ax, ay, aw, ah = (float(value) for value in first)
    bx, by, bw, bh = (float(value) for value in second)
    left = max(ax, bx)
    bottom = max(ay, by)
    right = min(ax + aw, bx + bw)
    top = min(ay + ah, by + bh)
    intersection = max(0.0, right - left) * max(0.0, top - bottom)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 1.0


def _limits_match(reference: list[float], candidate: list[float], *, autoscale: bool) -> bool:
    if len(reference) != 2 or len(candidate) != 2:
        return reference == candidate
    if not autoscale:
        return all(
            math.isclose(float(expected), float(actual), rel_tol=1e-9, abs_tol=1e-12)
            for expected, actual in zip(reference, candidate, strict=True)
        )
    span = max(abs(float(reference[1]) - float(reference[0])), 1e-12)
    return all(
        abs(float(expected) - float(actual)) <= 0.05 * span
        for expected, actual in zip(reference, candidate, strict=True)
    )


def compare_semantics(reference: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Return structural differences between two captured figure records."""

    differences: list[str] = []
    reference_axes = reference.get("axes", [])
    candidate_axes = candidate.get("axes", [])
    if len(reference_axes) != len(candidate_axes):
        return [f"axes count differs: {len(reference_axes)} != {len(candidate_axes)}"]

    if reference.get("figure_text") != candidate.get("figure_text"):
        differences.append("figure-level text differs")
    for index, (expected, actual) in enumerate(zip(reference_axes, candidate_axes, strict=True)):
        prefix = f"axes[{index}]"
        expected_bounds = expected.get("bounds", [])
        actual_bounds = actual.get("bounds", [])
        if len(expected_bounds) == 4 and len(actual_bounds) == 4:
            if any(
                abs(float(left) - float(right)) > 0.02
                for left, right in zip(expected_bounds, actual_bounds, strict=True)
            ):
                differences.append(f"{prefix} normalized bounds differ by more than 0.02")
            if _rect_iou(expected_bounds, actual_bounds) < 0.90:
                differences.append(f"{prefix} rectangle IoU is below 0.90")
        elif expected_bounds != actual_bounds:
            differences.append(f"{prefix} bounds are unavailable or differ")

        for field in (
            "projection",
            "xscale",
            "yscale",
            "x_inverted",
            "y_inverted",
            "title",
            "xlabel",
            "ylabel",
            "legend_text",
            "is_colorbar",
            "artist_families",
        ):
            if expected.get(field) != actual.get(field):
                differences.append(f"{prefix} {field} differs")
        for field in ("zscale", "z_inverted", "zlabel"):
            if field in expected and expected.get(field) != actual.get(field):
                differences.append(f"{prefix} {field} differs")
        if not _limits_match(
            expected.get("xlim", []),
            actual.get("xlim", []),
            autoscale=bool(expected.get("x_autoscale")),
        ):
            differences.append(f"{prefix} x limits differ")
        if not _limits_match(
            expected.get("ylim", []),
            actual.get("ylim", []),
            autoscale=bool(expected.get("y_autoscale")),
        ):
            differences.append(f"{prefix} y limits differ")
        if "zlim" in expected and not _limits_match(
            expected.get("zlim", []),
            actual.get("zlim", []),
            autoscale=bool(expected.get("z_autoscale")),
        ):
            differences.append(f"{prefix} z limits differ")
    return differences


def metrics_dict(metrics: VisualMetrics) -> dict[str, Any]:
    """JSON-friendly representation used by the gallery report."""

    return asdict(metrics)
