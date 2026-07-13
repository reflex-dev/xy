"""Matplotlib 3.11 additions and the last official 2-D plotting families."""

import numpy as np

import xy.pyplot as plt

fig, axes = plt.subplots(2, 2, figsize=(9, 7))

grouped = axes[0, 0].grouped_bar(
    [[2, 4, 3], [3, 2, 5]],
    tick_labels=["A", "B", "C"],
    labels=["before", "after"],
)
for container in grouped.bar_containers:
    axes[0, 0].bar_label(container, fmt="%.0f")
axes[0, 0].legend()

pie = axes[0, 1].pie([2, 3, 5], wedgeprops={"width": 0.35})
axes[0, 1].pie_label(pie, "{frac:.0%}")

stats = [
    {"med": 2, "q1": 1, "q3": 3, "whislo": 0, "whishi": 4, "fliers": [5]},
    {"med": 4, "q1": 3, "q3": 5, "whislo": 2, "whishi": 6, "fliers": []},
]
axes[1, 0].bxp(stats)
coords = np.linspace(-2, 2, 40)
axes[1, 0].violin(
    [
        {
            "coords": coords,
            "vals": np.exp(-(coords**2)),
            "mean": 0,
            "median": 0,
            "min": -2,
            "max": 2,
        }
    ],
    positions=[3],
)

axes[1, 1].table(
    cellText=[["north", 12], ["south", 18]],
    colLabels=["region", "value"],
    cellColours=[["#dbeafe", "#dbeafe"], ["#dcfce7", "#dcfce7"]],
)

fig.tight_layout()
