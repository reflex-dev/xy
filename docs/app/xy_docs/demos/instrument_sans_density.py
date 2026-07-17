"""Build the Instrument Sans point-density hero for the XY overview."""

from importlib.resources import files

import numpy as np
import reflex_xy
from PIL import Image, ImageDraw, ImageFont

import xy

N_POINTS = 40_000
N_INLIERS = round(N_POINTS * 0.97)
_RNG = np.random.default_rng(42)
_FONT = ImageFont.truetype(
    str(files("xy_docs").joinpath("assets/InstrumentSans-wdth-wght.ttf")),
    720,
)


def _glyph_mask(letter, x):
    image = Image.new("L", (1600, 1100))
    ImageDraw.Draw(image).text((x, 760), letter, font=_FONT, fill=255, anchor="ls")
    return np.asarray(image, dtype=float) / 255, image.getbbox()


_x_mask, _x_box = _glyph_mask("x", 140)
_y_mask, _y_box = _glyph_mask(
    "y",
    140 + _FONT.getlength("xy") - _FONT.getlength("y"),
)
_glyph_mask_xy = np.maximum(_x_mask, _y_mask)
_rows, _columns = np.nonzero(_glyph_mask_xy)
_left, _top, _right, _bottom = (
    _columns.min(),
    _rows.min(),
    _columns.max() + 1,
    _rows.max() + 1,
)
_pixels_per_unit = (_x_box[3] - _x_box[1]) / 16


def _inside(mask, points):
    pixels = np.rint(
        np.array([_left, _bottom]) + points * [_pixels_per_unit, -_pixels_per_unit]
    ).astype(int)
    valid = (
        (pixels[:, 0] >= 0)
        & (pixels[:, 0] < mask.shape[1])
        & (pixels[:, 1] >= 0)
        & (pixels[:, 1] < mask.shape[0])
    )
    result = np.zeros(len(points), dtype=bool)
    result[valid] = mask[pixels[valid, 1], pixels[valid, 0]] >= 0.06
    return result


def _sample_glyph(mask, box, count, correlation):
    x0, y0, x1, y1 = box
    bounds = np.array(
        [
            (x0 - _left) / _pixels_per_unit,
            (_bottom - y1) / _pixels_per_unit,
            (x1 - _left) / _pixels_per_unit,
            (_bottom - y0) / _pixels_per_unit,
        ]
    )
    center = bounds.reshape(2, 2).mean(axis=0)
    width, height = bounds[2:] - bounds[:2]
    sx, sy = width * 0.42, height * 0.44
    covariance = [
        [sx**2, correlation * sx * sy],
        [correlation * sx * sy, sy**2],
    ]

    accepted = []
    accepted_count = 0
    while accepted_count < count:
        batch = max(2048, (count - accepted_count) * 4)
        candidates = _RNG.multivariate_normal(center, covariance, batch)
        kept = candidates[_inside(mask, candidates)]
        accepted.append(kept)
        accepted_count += len(kept)
    return np.concatenate(accepted)[:count]


_n_x = round(N_INLIERS * 0.48)
_inliers = np.vstack(
    (
        _sample_glyph(_x_mask, _x_box, _n_x, 0.08),
        _sample_glyph(_y_mask, _y_box, N_INLIERS - _n_x, -0.10),
    )
)
_xlim = (-3.5, (_right - _left) / _pixels_per_unit + 3.5)
_ylim = (-3.5, (_bottom - _top) / _pixels_per_unit + 3.5)

_outlier_batches = []
_outlier_count = 0
while _outlier_count < N_POINTS - N_INLIERS:
    _batch = max(1024, (N_POINTS - N_INLIERS - _outlier_count) * 5)
    _source = _RNG.integers(0, N_INLIERS, _batch)
    _spread = _RNG.choice([0.65, 1.45, 2.75], _batch, p=[0.55, 0.32, 0.13])
    _spread *= np.sqrt(0.60)
    _candidates = np.column_stack(
        (
            _inliers[_source, 0] + _RNG.normal(0, _spread),
            _inliers[_source, 1] + _RNG.normal(0, _spread),
        )
    )
    _keep = ~_inside(_glyph_mask_xy, _candidates)
    _keep &= np.all(
        (_candidates >= [_xlim[0], _ylim[0]]) & (_candidates <= [_xlim[1], _ylim[1]]),
        axis=1,
    )
    _outlier_batches.append(_candidates[_keep])
    _outlier_count += _keep.sum()

_outliers = np.concatenate(_outlier_batches)[: N_POINTS - N_INLIERS]
_points = np.vstack((_inliers, _outliers))[_RNG.permutation(N_POINTS)]

_x_edges = np.arange(np.floor(_xlim[0]), np.ceil(_xlim[1]) + 1)
_y_edges = np.arange(np.floor(_ylim[0]), np.ceil(_ylim[1]) + 1)
_density = np.histogram2d(
    _inliers[:, 0],
    _inliers[:, 1],
    bins=(_x_edges, _y_edges),
)[0].T
_density = np.where(_density >= 8, _density, np.nan)

_stops = np.array(
    [
        [0.06, 0.055, 0.07],
        [0.10, 0.075, 0.13],
        [0.17, 0.12, 0.27],
        [0.26, 0.18, 0.43],
        [0.34, 0.25, 0.62],
        [0.431, 0.337, 0.812],
        [0.61, 0.53, 0.91],
    ]
)
_finite = np.isfinite(_density)
_lo, _hi = np.nanmin(_density), np.nanpercentile(_density, 98)
_scaled = np.clip((_density - _lo) / (_hi - _lo), 0, 1) ** 1.25
_position = np.nan_to_num(_scaled) * (len(_stops) - 1)
_lower = np.floor(_position).astype(int)
_upper = np.minimum(_lower + 1, len(_stops) - 1)
_mix = (_position - _lower)[..., None]
_rgb = _stops[_lower] * (1 - _mix) + _stops[_upper] * _mix
_rgba = np.concatenate(
    (_rgb, np.where(_finite, 0.96, 0)[..., None]),
    axis=-1,
)

_axis_style = {
    "grid_color": "rgba(76, 29, 149, 0.10)",
    "grid_width": 1,
    "axis_color": "rgba(17, 17, 19, 0.58)",
    "tick_color": "rgba(17, 17, 19, 0.58)",
    "tick_label_color": "#111113",
}
_chart = xy.chart(
    xy.scatter(*_points.T, size=1.85, color="#111113", opacity=1),
    xy.heatmap(
        _rgba,
        x=(_x_edges[:-1] + _x_edges[1:]) / 2,
        y=(_y_edges[:-1] + _y_edges[1:]) / 2,
        opacity=1,
    ),
    xy.x_axis(domain=_xlim, tick_count=8, style=_axis_style),
    xy.y_axis(domain=_ylim, tick_count=7, style=_axis_style),
    width=760,
    height=560,
    padding=(20, 22, 46, 54),
    hover=False,
    select=False,
    brush=False,
    crosshair=False,
)


def xy_density_hero():
    """Render the responsive Instrument Sans point-density hero."""
    return reflex_xy.chart(
        _chart,
        width="100%",
        height="min(74vw, 560px)",
        style={
            "--chart-modebar-bg": "var(--secondary-2)",
            "--chart-modebar-active": "var(--primary-a4)",
            "--chart-text": "var(--secondary-11)",
            "--chart-focus": "var(--primary-9)",
        },
    )
