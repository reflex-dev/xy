"""Render charts where the legend lands on the data, for the overlap report.

Each case is a typical dashboard card the builder emits: a small chart, a
handful of named series, default legend settings. Run from the repo root:
    uv run python examples/legend_overlap/make_cases.py
"""

from pathlib import Path

import numpy as np

import xy

OUT = Path(__file__).parent / "html"
OUT.mkdir(exist_ok=True)
rng = np.random.default_rng(7)
months = np.arange(12)
CARD = dict(width=520, height=300)


def growth(start, slope, noise=4):
    return start + slope * months + rng.normal(0, noise, 12).cumsum() * 0.3


def case_rising_lines(loc=None):
    marks = [
        xy.line(months, growth(40, 9), name="Revenue"),
        xy.line(months, growth(30, 7), name="Gross profit"),
        xy.line(months, growth(20, 5), name="Net income"),
    ]
    return xy.line_chart(*marks, xy.legend(loc=loc), title="Rising lines", **CARD)


def case_many_series(loc=None):
    regions = ["North", "South", "East", "West", "Central", "Online", "Wholesale", "Partners"]
    marks = [
        xy.line(months, growth(30 + 6 * i, 2 + i * 0.6), name=r) for i, r in enumerate(regions)
    ]
    return xy.line_chart(*marks, xy.legend(loc=loc), title="8 series", **CARD)


def case_long_names(loc=None):
    names = [
        "Monthly recurring revenue (USD)",
        "Customer acquisition cost (USD)",
        "Average contract value (USD)",
    ]
    marks = [xy.line(months, growth(40 - 8 * i, 6 - i), name=n) for i, n in enumerate(names)]
    return xy.line_chart(*marks, xy.legend(loc=loc), title="Long series names", **CARD)


def case_stacked_area(loc=None):
    base = np.zeros(12)
    marks = []
    for name, level in [("Desktop", 40), ("Mobile", 35), ("Tablet", 15)]:
        top = base + level + rng.normal(0, 3, 12)
        marks.append(xy.area(months, top, base=base.copy(), name=name, opacity=0.6))
        base = top
    return xy.area_chart(*marks, xy.legend(loc=loc), title="Stacked area (fills the plot)", **CARD)


def case_grouped_columns(loc=None):
    quarters = ["Q1", "Q2", "Q3", "Q4"]
    by_year = np.array([[54, 65, 77, 86], [60, 72, 85, 96], [63, 76, 89, 101]], dtype=float)
    mark = xy.column(quarters, by_year.T, series=["2024", "2025", "2026"], mode="grouped")
    return xy.chart(mark, xy.legend(loc=loc), title="Grouped columns", **CARD)


def case_small_card(loc=None):
    marks = [
        xy.line(months, growth(40, 9), name="Signups"),
        xy.line(months, growth(35, 8), name="Activations"),
        xy.line(months, growth(25, 6), name="Paid conversions"),
    ]
    return xy.line_chart(
        *marks, xy.legend(loc=loc), title="Small card (320x200)", width=320, height=200
    )


def case_work_orders(loc=None):
    """The builder chart from the report: stacked horizontal bars at the axis max."""
    stores = ["Bismarck", "Fargo", "Grand Forks", "Jamestown", "Minot", "West Fargo"]
    counts = np.full((len(stores), 4), 4.0)
    mark = xy.bar(
        stores,
        counts,
        series=["Waiting Parts", "In Progress", "Waiting Approval", "Complete"],
        colors=["#f2c12e", "#7a8899", "#ddd8d6", "#2e8b57"],
        mode="stacked",
        orientation="horizontal",
    )
    return xy.chart(
        mark,
        xy.x_axis(label="Work orders"),
        xy.y_axis(label="Store"),
        xy.legend(loc=loc),
        title="Work orders by store",
        width=900,
        height=360,
    )


CASES = {
    "1_rising_lines": case_rising_lines,
    "2_many_series": case_many_series,
    "3_long_names": case_long_names,
    "4_stacked_area": case_stacked_area,
    "5_grouped_columns": case_grouped_columns,
    "6_small_card": case_small_card,
    "7_work_orders": case_work_orders,
}

if __name__ == "__main__":
    for key, build in CASES.items():
        for loc in (None, "best", "outside top"):
            tag = {None: "default", "best": "best", "outside top": "outside_top"}[loc]
            rng = np.random.default_rng(7)  # same data for both variants
            globals()["rng"] = rng
            build(loc).to_html(OUT / f"{key}__{tag}.html")
            print("wrote", key, tag)
