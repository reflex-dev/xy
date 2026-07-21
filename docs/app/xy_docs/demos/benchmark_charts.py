"""Live XY charts for the public launch-benchmark documentation."""

from __future__ import annotations

import reflex as rx
import reflex_xy

import xy

XY_COLOR = "#6E56CF"
MATPLOTLIB_COLOR = "#8B8D98"
PLOTLY_COLOR = "#B9BBC6"
SERIES = (
    ("XY", XY_COLOR),
    ("Matplotlib", MATPLOTLIB_COLOR),
    ("Plotly", PLOTLY_COLOR),
)

_CHART_CLASS = (
    "w-full [--benchmark-bg:#ffffff] [--benchmark-plot:#fcfcfd] "
    "[--benchmark-grid:#e8e8ec] [--benchmark-axis:#d9d9e0] "
    "[--benchmark-text:#60646c] dark:[--benchmark-bg:#09090b] "
    "dark:[--benchmark-plot:#111113] dark:[--benchmark-grid:#27272a] "
    "dark:[--benchmark-axis:#3f3f46] dark:[--benchmark-text:#d4d4d8]"
)
_CARD_CLASS = (
    "w-full overflow-hidden rounded-xl border border-secondary-4 bg-white "
    "shadow-[0_12px_32px_#1c20240f] dark:bg-black"
)
_PANEL_CLASS = (
    "min-w-0 overflow-hidden rounded-xl border border-secondary-4 "
    "bg-white shadow-[0_8px_24px_#1c20240a] dark:bg-black"
)


def _theme() -> xy.Theme:
    """Return the neutral benchmark theme shared by every live chart."""
    return xy.theme(
        background="var(--benchmark-bg, #ffffff)",
        plot_background="var(--benchmark-plot, #fcfcfd)",
        grid_color="var(--benchmark-grid, #e8e8ec)",
        axis_color="var(--benchmark-axis, #d9d9e0)",
        text_color="var(--benchmark-text, #60646c)",
    )


def _legend() -> rx.Component:
    """Render the compact Reflex legend used by both benchmark cards."""
    return rx.el.div(
        *(
            rx.el.div(
                rx.el.span(
                    class_name="size-2.5 shrink-0 rounded-full",
                    style={"background": color},
                    aria_hidden="true",
                ),
                rx.el.span(label),
                class_name=(
                    "inline-flex items-center gap-1 whitespace-nowrap text-[0.65625rem] "
                    "font-semibold text-secondary-11"
                ),
            )
            for label, color in SERIES
        ),
        class_name="flex shrink-0 flex-wrap items-center justify-end gap-x-2 gap-y-2",
        aria_label="Benchmark series legend",
    )


def _heading(title: str, subtitle: str, *, show_legend: bool = True) -> rx.Component:
    """Render benchmark title, methodology subtitle, and optional legend."""
    return rx.el.div(
        rx.el.div(
            rx.el.h3(
                title,
                class_name="text-xl font-semibold tracking-[-0.02em] text-secondary-12",
            ),
            rx.el.p(
                subtitle,
                class_name="mt-1 text-sm font-medium text-secondary-10",
            ),
            class_name="min-w-0 flex-1",
        ),
        _legend() if show_legend else rx.fragment(),
        class_name=(
            "flex flex-col gap-4 px-5 pt-5 sm:px-4 sm:pt-7 lg:flex-row "
            "lg:items-start lg:justify-between"
        ),
    )


_SNAPSHOT_CATEGORIES = [
    "Static CPU PNG",
    "Interactive · default GPU",
    "Interactive · CPU fallback",
]
_SNAPSHOT_VALUES = [
    [0.0232, 0.1797, 0.9920],
    [2.7842, 3.0029, 3.6735],
    [9.5834, 3.6434, 8.2152],
]

_SNAPSHOT_CHART = xy.bar_chart(
    xy.bar(
        _SNAPSHOT_CATEGORIES,
        _SNAPSHOT_VALUES,
        orientation="horizontal",
        mode="grouped",
        series=[label for label, _color in SERIES],
        colors=[color for _label, color in SERIES],
        opacity=1,
        # Square ends keep the true 1–2 px linear bar visible; a rounded cap
        # collapses this particular value into a dot at the current scale.
        corner_radius=0,
        stroke_width=1,
    ),
    xy.tooltip(title="{x}", format={"y": ".4f s"}),
    xy.legend(show=False),
    xy.modebar(show=False),
    xy.interaction_config(navigation=False),
    xy.x_axis(
        label="Render time (seconds) · lower is better",
        domain=(0, 10),
        tick_values=[0, 2, 4, 6, 8, 10],
        tick_labels=["0 s", "2 s", "4 s", "6 s", "8 s", "10 s"],
        style={"grid_width": 1, "grid_opacity": 1},
    ),
    xy.y_axis(
        reverse=True,
        style={"grid_opacity": 0, "axis_width": 0, "tick_width": 0},
    ),
    _theme(),
    width="100%",
    height=430,
    padding=(18, 30, 58, 170),
    class_name=_CHART_CLASS,
)


def launch_snapshot_demo() -> rx.Component:
    """Render the 10M comparison as a live grouped horizontal bar chart."""
    return rx.el.section(
        _heading(
            "10M-point cold-render time",
            "900×420 output · mean of three isolated runs · shared linear scale",  # noqa: RUF001
        ),
        rx.el.div(
            rx.el.div(
                reflex_xy.chart(_SNAPSHOT_CHART, height="430px"),
                rx.el.span(
                    class_name=(
                        "pointer-events-none absolute left-[170px] top-[30px] "
                        "h-[31px] w-2 bg-[#6E56CF]"
                    ),
                    aria_hidden="true",
                ),
                class_name="relative",
            ),
            class_name="px-2 pb-2 sm:px-4 sm:pb-4",
        ),
        class_name=_CARD_CLASS,
        aria_label="10-million-point cold-render benchmark comparison",
    )


_SIZE_LABELS = ["10k", "100k", "1M", "10M", "1B"]
_XY_SCALING_VALUES = [0.0085, 0.0108, 0.0114, 0.0232, 1.1452]
_MATPLOTLIB_SCALING_VALUES = [0.0234, 0.0475, 0.2946, 2.7842]
_PLOTLY_SCALING_VALUES = [1.8830, 1.9496, 2.6490, 9.5834]

_SCALING_CHART = xy.line_chart(
    xy.line(
        _SIZE_LABELS,
        _XY_SCALING_VALUES,
        name="XY",
        color=XY_COLOR,
        width=2.5,
    ),
    xy.line(
        _SIZE_LABELS[:4],
        _MATPLOTLIB_SCALING_VALUES,
        name="Matplotlib",
        color=MATPLOTLIB_COLOR,
        width=2,
    ),
    xy.line(
        _SIZE_LABELS[:4],
        _PLOTLY_SCALING_VALUES,
        name="Plotly",
        color=PLOTLY_COLOR,
        width=2,
    ),
    *(
        xy.marker(
            size,
            value,
            text=label,
            size=9,
            dx=0,
            dy=-11,
            anchor="middle",
            color=XY_COLOR,
        )
        for size, value, label in zip(
            _SIZE_LABELS,
            _XY_SCALING_VALUES,
            ["8.5 ms", "10.8 ms", "11.4 ms", "23.2 ms", "1.145 s"],
            strict=True,
        )
    ),
    *(
        xy.marker(
            size,
            value,
            text=label,
            size=9,
            dx=0,
            dy=-27,
            anchor="middle",
            color=MATPLOTLIB_COLOR,
        )
        for size, value, label in zip(
            _SIZE_LABELS[:4],
            _MATPLOTLIB_SCALING_VALUES,
            ["23.4 ms", "47.5 ms", "0.295 s", "2.784 s"],
            strict=True,
        )
    ),
    *(
        xy.marker(
            size,
            value,
            text=label,
            size=9,
            dx=0,
            dy=16 if size == "10M" else -11,
            anchor="middle",
            color=PLOTLY_COLOR,
        )
        for size, value, label in zip(
            _SIZE_LABELS[:4],
            _PLOTLY_SCALING_VALUES,
            ["1.883 s", "1.950 s", "2.649 s", "9.583 s"],
            strict=True,
        )
    ),
    xy.vline(
        "1M",
        text="Density threshold",
        color=XY_COLOR,
        opacity=0.28,
        width=1.5,
    ),
    xy.text(
        "1B",
        9.6,
        "× Plotly · failed",  # noqa: RUF001
        dx=-4,
        anchor="end",
        color=PLOTLY_COLOR,
    ),
    xy.text(
        "1B",
        8.7,
        "× Matplotlib · >36 GiB",  # noqa: RUF001
        dx=-4,
        anchor="end",
        color=MATPLOTLIB_COLOR,
    ),
    xy.tooltip(format={"y": ".4f s"}),
    xy.legend(show=False),
    xy.modebar(show=False),
    xy.interaction_config(navigation=False),
    xy.x_axis(tick_label_anchor="center"),
    xy.y_axis(
        label="Render time (seconds)",
        label_position="center",
        domain=(0, 10.5),
        tick_values=[0, 2, 4, 6, 8, 10],
        tick_labels=["0 s", "2 s", "4 s", "6 s", "8 s", "10 s"],
        style={"grid_width": 1, "grid_opacity": 1},
    ),
    _theme(),
    width="100%",
    height=360,
    padding=(18, 24, 44, 68),
    class_name=_CHART_CLASS,
)

_MEMORY_CATEGORIES = ["XY", "Matplotlib", "Plotly / Kaleido"]
_MEMORY_VALUES = [0.283, 0.834, 5.671]
_MEMORY_CHART = xy.bar_chart(
    *(
        xy.bar(
            [category],
            [value],
            name=category,
            orientation="horizontal",
            color=color,
            opacity=1,
            corner_radius=6,
        )
        for category, value, color in zip(
            _MEMORY_CATEGORIES,
            _MEMORY_VALUES,
            (XY_COLOR, MATPLOTLIB_COLOR, PLOTLY_COLOR),
            strict=True,
        )
    ),
    xy.text(0.42, "XY", "0.283", color="var(--benchmark-text, #60646c)"),
    xy.text(0.98, "Matplotlib", "0.834", color="var(--benchmark-text, #60646c)"),
    xy.text(
        5.48,
        "Plotly / Kaleido",
        "5.671",
        anchor="end",
        color="var(--benchmark-text, #60646c)",
    ),
    xy.tooltip(format={"y": ".3f GiB"}),
    xy.legend(show=False),
    xy.modebar(show=False),
    xy.interaction_config(navigation=False),
    xy.x_axis(
        label="Peak process-tree RSS (GiB)",
        domain=(0, 6),
        tick_values=[0, 2, 4, 6],
        tick_labels=["0", "2", "4", "6 GiB"],
        style={"grid_width": 1, "grid_opacity": 1},
    ),
    xy.y_axis(
        reverse=True,
        style={"grid_opacity": 0, "axis_width": 0, "tick_width": 0},
    ),
    _theme(),
    width="100%",
    height=260,
    padding=(16, 22, 46, 110),
    class_name=_CHART_CLASS,
)


def _panel(
    title: str,
    subtitle: str,
    chart: xy.Chart,
    *,
    height: str,
    show_legend: bool = False,
) -> rx.Component:
    """Wrap one XY chart in a titled responsive panel."""
    return rx.el.section(
        rx.el.div(
            rx.el.div(
                rx.el.h3(
                    title,
                    class_name="text-lg font-semibold tracking-[-0.01em] text-secondary-12",
                ),
                rx.el.p(
                    subtitle,
                    class_name="mt-1 text-sm font-medium text-secondary-10",
                ),
                class_name="min-w-0 flex-1",
            ),
            _legend() if show_legend else rx.fragment(),
            class_name=(
                "flex flex-col gap-3 px-5 pb-2 pt-5 sm:flex-row "
                "sm:items-start sm:justify-between sm:px-6 sm:pt-6"
            ),
        ),
        rx.el.div(
            reflex_xy.chart(chart, height=height),
            class_name="px-2 pb-2 sm:px-3 sm:pb-3",
        ),
        class_name=_PANEL_CLASS,
    )


def scaling_and_memory_demo() -> rx.Component:
    """Render coordinated live scaling-time and peak-memory charts."""
    return rx.el.div(
        _panel(
            "Static render time by input size",
            "Static 900×420 PNG · measured runs · × marks guarded failures",  # noqa: RUF001
            _SCALING_CHART,
            height="360px",
            show_legend=True,
        ),
        _panel(
            "10M static peak RSS",
            "Static 900×420 PNG · complete process tree · GiB",  # noqa: RUF001
            _MEMORY_CHART,
            height="260px",
        ),
        class_name="grid w-full grid-cols-1 gap-5",
        aria_label="Launch benchmark scaling time and peak memory",
    )


__all__ = ["launch_snapshot_demo", "scaling_and_memory_demo"]
