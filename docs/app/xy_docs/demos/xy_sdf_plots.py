"""Interactive Instrument Sans ``xy`` plots derived from one signed-distance PDF."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

import numpy as np
import reflex as rx
import reflex_xy
from PIL import Image, ImageDraw, ImageFont

import xy


@dataclass(frozen=True)
class SDFPlotConfig:
    """Parameters shared by all four plots."""

    text: str = "xy"
    font_size: int = 720
    x_height_bins: float = 18.0
    sample_points: int = 50_000
    density_points: int = 1_000_000
    density_display_points: int = 250_000
    core_sigma: float = 1.0
    halo_sigma: float = 3.0
    halo_weight: float = 0.125
    max_sdf: float = 10.0
    view_padding: float = 10.0
    bin_size: float = 1.0
    bin_min_count: int = 25
    bin_gradient_gamma: float = 1.25
    heatmap_gamma: float = 0.25
    heatmap_stride: int = 16
    contour_cells_per_bin: float = 13.5
    contour_high_level: float = 0.85
    contour_level_ratio: float = 0.46
    contour_width: float = 2.2
    density_size_offset: float = 1.0
    density_size_scale: float = 0.5
    chart_height: int = 560
    seed: int = 42


@dataclass(frozen=True)
class SDFPalette:
    """Colors shared across the light and dark plot variants."""

    light_background: str = "#FCFCFD"
    dark_background: str = "#090A0B"
    point: str = "#111113"
    purple: str = "#6E56CF"
    bin_gradient: tuple[tuple[float, float, float], ...] = (
        (0.06, 0.055, 0.07),
        (0.10, 0.075, 0.13),
        (0.17, 0.12, 0.27),
        (0.26, 0.18, 0.43),
        (0.34, 0.25, 0.62),
        (0.431, 0.337, 0.812),
        (0.61, 0.53, 0.91),
    )
    heatmap_gradient: tuple[tuple[float, float, float], ...] = (
        (0.035, 0.039, 0.043),
        (0.055, 0.040, 0.085),
        (0.10, 0.04, 0.18),
        (0.24, 0.07, 0.45),
        (0.48, 0.13, 0.82),
        (0.73, 0.32, 1.00),
        (0.90, 0.72, 1.00),
    )


@dataclass(frozen=True)
class SDFPlots:
    """The four charts in documentation reading order."""

    bins_scatter: xy.Chart
    heatmap: xy.Chart
    contours: xy.Chart
    million_scatter: xy.Chart

    @property
    def reading_order(self) -> tuple[xy.Chart, ...]:
        """Return bins/scatter, heatmap, contours, then one-million scatter."""
        return (
            self.bins_scatter,
            self.heatmap,
            self.contours,
            self.million_scatter,
        )


@dataclass(frozen=True)
class _Raster:
    inside: np.ndarray
    x_bbox: tuple[int, int, int, int]
    xy_bbox: tuple[int, int, int, int]
    pixels_per_bin: float


@dataclass(frozen=True)
class _Model:
    raster: _Raster
    pdf: np.ndarray
    xlim: tuple[float, float]
    ylim: tuple[float, float]


DEFAULT_CONFIG = SDFPlotConfig()
DEFAULT_PALETTE = SDFPalette()
_FONT_PATH = files("xy_docs").joinpath("assets/InstrumentSans-wdth-wght.ttf")
_CHART_TOKENS = {
    "--chart-text": "var(--secondary-11)",
    "--chart-focus": "var(--primary-9)",
}


class _SDFPlotError(ValueError):
    """Invalid demo configuration or font rasterization."""

    @classmethod
    def halo_weight(cls) -> _SDFPlotError:
        return cls("halo_weight must be between 0 and 1")

    @classmethod
    def positive(cls, names: list[str]) -> _SDFPlotError:
        return cls(f"{', '.join(names)} must be positive")

    @classmethod
    def sample_count(cls) -> _SDFPlotError:
        return cls("display sample counts cannot exceed density_points")

    @classmethod
    def empty_glyph(cls) -> _SDFPlotError:
        return cls("Instrument Sans produced an empty glyph mask")


def _validate(config: SDFPlotConfig) -> None:
    if not 0 <= config.halo_weight <= 1:
        raise _SDFPlotError.halo_weight()
    positive = {
        "font_size": config.font_size,
        "x_height_bins": config.x_height_bins,
        "sample_points": config.sample_points,
        "density_points": config.density_points,
        "density_display_points": config.density_display_points,
        "core_sigma": config.core_sigma,
        "halo_sigma": config.halo_sigma,
        "max_sdf": config.max_sdf,
        "bin_size": config.bin_size,
        "heatmap_stride": config.heatmap_stride,
        "contour_cells_per_bin": config.contour_cells_per_bin,
        "chart_height": config.chart_height,
    }
    invalid = [name for name, value in positive.items() if value <= 0]
    if invalid:
        raise _SDFPlotError.positive(invalid)
    if max(config.sample_points, config.density_display_points) > config.density_points:
        raise _SDFPlotError.sample_count()


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    rows, columns = np.nonzero(mask)
    if not len(columns):
        raise _SDFPlotError.empty_glyph()
    return (
        int(columns.min()),
        int(rows.min()),
        int(columns.max() + 1),
        int(rows.max() + 1),
    )


def _rasterize(config: SDFPlotConfig) -> _Raster:
    font = ImageFont.truetype(str(_FONT_PATH), config.font_size)
    text_bbox = font.getbbox(config.text, anchor="ls")
    x_font_bbox = font.getbbox("x", anchor="ls")
    pixels_per_bin = (x_font_bbox[3] - x_font_bbox[1]) / config.x_height_bins
    pad = int(np.ceil((config.max_sdf + 2) * pixels_per_bin))
    left = min(text_bbox[0], x_font_bbox[0])
    top = min(text_bbox[1], x_font_bbox[1])
    right = max(text_bbox[2], x_font_bbox[2])
    bottom = max(text_bbox[3], x_font_bbox[3])
    canvas_size = (right - left + 2 * pad + 2, bottom - top + 2 * pad + 2)
    origin = (pad - left, pad - top)

    xy_image = Image.new("L", canvas_size, 0)
    ImageDraw.Draw(xy_image).text(origin, config.text, font=font, fill=255, anchor="ls")
    inside = np.asarray(xy_image, dtype=np.float32) >= 127.5

    x_image = Image.new("L", canvas_size, 0)
    ImageDraw.Draw(x_image).text(origin, "x", font=font, fill=255, anchor="ls")
    return _Raster(
        inside=inside,
        x_bbox=_bbox(np.asarray(x_image) >= 127.5),
        xy_bbox=_bbox(inside),
        pixels_per_bin=pixels_per_bin,
    )


def _squared_distance_transform_1d(values: np.ndarray) -> np.ndarray:
    """Compute the lower envelope of squared-distance parabolas in linear time."""
    finite_sites = np.flatnonzero(np.isfinite(values))
    if not finite_sites.size:
        return np.full(values.shape, np.inf)

    size = values.size
    sites = np.empty(size, dtype=np.intp)
    boundaries = np.empty(size + 1, dtype=float)
    envelope_size = 0
    sites[0] = finite_sites[0]
    boundaries[0] = -np.inf
    boundaries[1] = np.inf

    for site in finite_sites[1:]:
        previous = sites[envelope_size]
        boundary = (values[site] + site * site - values[previous] - previous * previous) / (
            2 * (site - previous)
        )
        while boundary <= boundaries[envelope_size]:
            envelope_size -= 1
            previous = sites[envelope_size]
            boundary = (values[site] + site * site - values[previous] - previous * previous) / (
                2 * (site - previous)
            )
        envelope_size += 1
        sites[envelope_size] = site
        boundaries[envelope_size] = boundary
        boundaries[envelope_size + 1] = np.inf

    result = np.empty(size, dtype=float)
    envelope_index = 0
    for position in range(size):
        while boundaries[envelope_index + 1] < position:
            envelope_index += 1
        offset = position - sites[envelope_index]
        result[position] = offset * offset + values[sites[envelope_index]]
    return result


def _distance_transform_edt(mask: np.ndarray) -> np.ndarray:
    """Return exact Euclidean distances from true cells to the nearest false cell."""
    squared = np.where(mask, np.inf, 0.0)
    for row in range(squared.shape[0]):
        squared[row] = _squared_distance_transform_1d(squared[row])
    for column in range(squared.shape[1]):
        squared[:, column] = _squared_distance_transform_1d(squared[:, column])
    return np.sqrt(squared)


def _build_model(config: SDFPlotConfig) -> _Model:
    raster = _rasterize(config)
    inside_distance = _distance_transform_edt(raster.inside)
    outside_distance = _distance_transform_edt(~raster.inside)
    sdf = (
        np.where(
            raster.inside,
            -(inside_distance - 0.5),
            outside_distance - 0.5,
        )
        / raster.pixels_per_bin
    )

    outside = np.maximum(sdf, 0)
    core = np.exp(-0.5 * (outside / config.core_sigma) ** 2)
    halo = np.exp(-0.5 * (outside / config.halo_sigma) ** 2)
    pdf = np.where(
        sdf <= 0,
        1.0,
        (1 - config.halo_weight) * core + config.halo_weight * halo,
    )
    pdf[sdf >= config.max_sdf] = 0

    x_left = raster.x_bbox[0] - 0.5
    x_bottom = raster.x_bbox[3] - 0.5
    xy_left, xy_top, xy_right, xy_bottom = raster.xy_bbox
    mask_xlim = (
        (xy_left - 0.5 - x_left) / raster.pixels_per_bin,
        (xy_right - 0.5 - x_left) / raster.pixels_per_bin,
    )
    mask_ylim = (
        (x_bottom - (xy_bottom - 0.5)) / raster.pixels_per_bin,
        (x_bottom - (xy_top - 0.5)) / raster.pixels_per_bin,
    )
    return _Model(
        raster=raster,
        pdf=pdf,
        xlim=(mask_xlim[0] - config.view_padding, mask_xlim[1] + config.view_padding),
        ylim=(mask_ylim[0] - config.view_padding, mask_ylim[1] + config.view_padding),
    )


def _sample(model: _Model, count: int, seed: int) -> tuple[np.ndarray, ...]:
    rng = np.random.default_rng(seed)
    probabilities = (model.pdf / model.pdf.sum()).ravel()
    chosen = rng.choice(probabilities.size, count, replace=True, p=probabilities)
    row, column = np.divmod(chosen, model.pdf.shape[1])
    raster = model.raster
    x = (column + rng.uniform(-0.5, 0.5, count) - (raster.x_bbox[0] - 0.5)) / raster.pixels_per_bin
    y = (raster.x_bbox[3] - 0.5 - row - rng.uniform(-0.5, 0.5, count)) / raster.pixels_per_bin
    return x, y, model.pdf[row, column]


def _grid(model: _Model, stride: int) -> tuple[np.ndarray, ...]:
    row = np.arange(0, model.pdf.shape[0], stride)
    column = np.arange(0, model.pdf.shape[1], stride)
    raster = model.raster
    x = (column - (raster.x_bbox[0] - 0.5)) / raster.pixels_per_bin
    y_descending = (raster.x_bbox[3] - 0.5 - row) / raster.pixels_per_bin
    return model.pdf[np.ix_(row, column)][::-1], x, y_descending[::-1]


def _interpolate(values: np.ndarray, stops: np.ndarray) -> np.ndarray:
    position = values * (len(stops) - 1)
    lower = np.floor(position).astype(int)
    upper = np.minimum(lower + 1, len(stops) - 1)
    mix = (position - lower)[..., None]
    return stops[lower] * (1 - mix) + stops[upper] * mix


def _bin_colors(counts: np.ndarray, config: SDFPlotConfig, palette: SDFPalette) -> np.ndarray:
    finite = np.isfinite(counts)
    rgba = np.zeros((*counts.shape, 4), dtype=float)
    if not finite.any():
        return rgba
    visible = counts[finite]
    low = float(visible.min())
    high = float(np.percentile(visible, 98))
    scaled = np.zeros_like(counts, dtype=float)
    scaled[finite] = np.clip((visible - low) / max(high - low, 1e-12), 0, 1)
    rgba[..., :3] = _interpolate(
        scaled**config.bin_gradient_gamma,
        np.asarray(palette.bin_gradient),
    )
    rgba[..., 3] = np.where(finite, 0.96, 0)
    return rgba


def _heatmap_colors(pdf: np.ndarray, config: SDFPlotConfig, palette: SDFPalette) -> np.ndarray:
    clipped = np.clip(pdf, 0, 1)
    background = palette.dark_background.removeprefix("#")
    background_rgb = np.array([int(background[index : index + 2], 16) for index in (0, 2, 4)]) / 255
    rgba = np.empty((*pdf.shape, 4), dtype=float)
    rgba[..., :3] = _interpolate(
        clipped**config.heatmap_gamma,
        np.asarray(palette.heatmap_gradient),
    )
    rgba[clipped == 0, :3] = background_rgb
    rgba[..., 3] = 1
    return rgba


def _chart(
    *marks: xy.Mark,
    model: _Model,
    config: SDFPlotConfig,
) -> xy.Chart:
    x_span = model.xlim[1] - model.xlim[0]
    y_span = model.ylim[1] - model.ylim[0]
    width = round(config.chart_height * x_span / y_span)
    return xy.chart(
        *marks,
        xy.x_axis(domain=model.xlim, tick_label_strategy="none"),
        xy.y_axis(domain=model.ylim, tick_label_strategy="none"),
        xy.legend(show=False),
        width=width,
        height=config.chart_height,
        padding=(0, 0, 0, 0),
        hover=False,
        select=False,
        brush=False,
        crosshair=False,
    )


@lru_cache(maxsize=4)
def build_sdf_plots(
    config: SDFPlotConfig = DEFAULT_CONFIG,
    palette: SDFPalette = DEFAULT_PALETTE,
) -> SDFPlots:
    """Compute the shared model and build every chart in one cached pass."""
    _validate(config)
    model = _build_model(config)
    x, y, sampled_pdf = _sample(model, config.density_points, config.seed)
    sample_slice = slice(0, config.sample_points)

    x_edges = np.arange(
        np.floor(model.xlim[0] / config.bin_size) * config.bin_size,
        np.ceil(model.xlim[1] / config.bin_size) * config.bin_size + config.bin_size,
        config.bin_size,
    )
    y_edges = np.arange(
        np.floor(model.ylim[0] / config.bin_size) * config.bin_size,
        np.ceil(model.ylim[1] / config.bin_size) * config.bin_size + config.bin_size,
        config.bin_size,
    )
    counts = np.histogram2d(x[sample_slice], y[sample_slice], bins=(x_edges, y_edges))[0].T
    visible_counts = np.where(counts >= config.bin_min_count, counts, np.nan)
    bins_scatter = _chart(
        xy.scatter(
            x[sample_slice],
            y[sample_slice],
            size=1.65,
            color=palette.point,
            opacity=0.48,
            density=False,
        ),
        xy.heatmap(
            _bin_colors(visible_counts, config, palette),
            x=(x_edges[:-1] + x_edges[1:]) / 2,
            y=(y_edges[:-1] + y_edges[1:]) / 2,
        ),
        model=model,
        config=config,
    )

    heatmap_pdf, heatmap_x, heatmap_y = _grid(model, config.heatmap_stride)
    heatmap = _chart(
        xy.heatmap(
            _heatmap_colors(heatmap_pdf, config, palette),
            x=heatmap_x,
            y=heatmap_y,
        ),
        model=model,
        config=config,
    )

    contour_stride = max(
        1,
        round(model.raster.pixels_per_bin / config.contour_cells_per_bin),
    )
    contour_pdf, contour_x, contour_y = _grid(model, contour_stride)
    contour_levels = tuple(
        config.contour_high_level * config.contour_level_ratio**index
        for index in range(len(palette.bin_gradient))
    )
    contour_colors = tuple(
        "#" + "".join(f"{round(channel * 255):02X}" for channel in stop)
        for stop in reversed(palette.bin_gradient)
    )
    contours = _chart(
        *(
            xy.contour(
                contour_pdf,
                x=contour_x,
                y=contour_y,
                levels=(level,),
                color=color,
                width=config.contour_width,
                opacity=0.98,
            )
            for level, color in zip(contour_levels, contour_colors, strict=True)
        ),
        model=model,
        config=config,
    )

    display_slice = slice(0, config.density_display_points)
    display_pdf = sampled_pdf[display_slice]
    sizes = config.density_size_offset + config.density_size_scale * np.clip(display_pdf, 0, 1)
    million_scatter = _chart(
        xy.scatter(
            x[display_slice],
            y[display_slice],
            size=sizes,
            size_range=(float(sizes.min()), float(sizes.max())),
            color=palette.purple,
            opacity=1,
            density=False,
        ),
        model=model,
        config=config,
    )
    return SDFPlots(bins_scatter, heatmap, contours, million_scatter)


def _responsive_chart(chart: xy.Chart, background: str) -> rx.Component:
    return reflex_xy.chart(
        chart,
        width="100%",
        height="auto",
        aspect_ratio=f"{chart.width} / {chart.height}",
        style={
            **_CHART_TOKENS,
            "--chart-bg": background,
            "background": background,
        },
    )


def xy_sdf_plot_grid(
    config: SDFPlotConfig = DEFAULT_CONFIG,
    palette: SDFPalette = DEFAULT_PALETTE,
) -> rx.Component:
    """Render all four cached charts as a zero-gap responsive grid."""
    plots = build_sdf_plots(config, palette)
    backgrounds = (
        palette.light_background,
        palette.dark_background,
        palette.dark_background,
        palette.light_background,
    )
    return rx.el.div(
        *(
            _responsive_chart(chart, background)
            for chart, background in zip(
                plots.reading_order,
                backgrounds,
                strict=True,
            )
        ),
        id="xy-sdf-plot-grid",
        class_name="grid w-full grid-cols-1 gap-0 overflow-hidden md:grid-cols-2",
    )


__all__ = [
    "DEFAULT_CONFIG",
    "DEFAULT_PALETTE",
    "SDFPalette",
    "SDFPlotConfig",
    "SDFPlots",
    "build_sdf_plots",
    "xy_sdf_plot_grid",
]
