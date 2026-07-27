"""Generate matched browser evidence for the box customizability audit."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

import xy


def samples() -> list[np.ndarray]:
    rng = np.random.default_rng(24)
    return [
        np.concatenate((rng.normal(62, 7, 180), [38, 84])),
        np.concatenate((rng.normal(73, 9, 180), [44, 101])),
        np.concatenate((rng.normal(68, 6, 180), [47, 89])),
    ]


def chart(mode: str) -> xy.Chart:
    marks: list[xy.Component] = []
    colors = ["#818cf8", "#38bdf8", "#2dd4bf"]
    names = ["Core", "Growth", "Enterprise"]
    for position, (values, color, name) in enumerate(zip(samples(), colors, names, strict=True)):
        kwargs: dict[str, object] = {}
        if mode == "after":
            kwargs["style"] = {
                "fill": color,
                "fill-opacity": 0.28,
                "stroke": color,
                "stroke-width": 2,
                "stroke-opacity": 1,
            }
            kwargs["median_style"] = {
                "stroke": "#f8fafc",
                "stroke-width": 3,
            }
            kwargs["whisker_style"] = {
                "stroke": color,
                "stroke-width": 1.5,
                "stroke-opacity": 0.75,
            }
            kwargs["outlier_style"] = {
                "fill": "#0f172a",
                "stroke": color,
                "stroke-width": 2,
                "marker-shape": "diamond",
            }
        marks.append(
            xy.box(
                values,
                x=np.full(len(values), position),
                name=name,
                color=color,
                width=0.48,
                opacity=0.88,
                outlier_size=7,
                **kwargs,
            )
        )

    return xy.box_chart(
        *marks,
        xy.x_axis(
            domain=(-0.65, 2.65),
            tick_values=[0, 1, 2],
            tick_labels=names,
            grid=False,
            style={
                "axis_color": "#334155",
                "tick_color": "#64748b",
                "tick_label_color": "#cbd5e1",
                "tick_label_size": 13,
            },
        ),
        xy.y_axis(
            label="Response time (ms)",
            domain=(25, 110),
            style={
                "axis_color": "#334155",
                "grid_color": "#334155",
                "grid_opacity": 0.65,
                "tick_color": "#64748b",
                "tick_label_color": "#94a3b8",
                "label_color": "#cbd5e1",
            },
        ),
        xy.legend(show=False),
        xy.theme(
            background="#0b1120",
            plot_background="#0b1120",
            text_color="#e2e8f0",
            grid_color="#334155",
            axis_color="#475569",
        ),
        title=(
            "Box plot customization — "
            + (
                "before: one paint for every part"
                if mode == "before"
                else "after: each part styled"
            )
        ),
        width=700,
        height=430,
        padding=(48, 28, 58, 70),
        style={"background": "#0b1120"},
        styles={
            "title": {
                "font_size": 17,
                "font_weight": 700,
                "letter_spacing": "-0.02em",
            }
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("before", "after"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    chart(args.mode).to_html(
        args.output,
        custom_css="""
html, body { margin: 0; width: 100%; height: 100%; background: #0b1120; }
body { display: grid; place-items: center; overflow: hidden; }
""",
    )


if __name__ == "__main__":
    main()
