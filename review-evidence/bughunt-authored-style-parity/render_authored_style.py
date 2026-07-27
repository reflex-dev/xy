from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


engine, destination = sys.argv[1:3]
if engine == "matplotlib":
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
else:
    import xy.pyplot as plt


with plt.style.context("dark_background"):
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    fig.subplots_adjust(left=0.20, right=0.95, bottom=0.22, top=0.80)
    x = np.arange(4)
    values = np.asarray([2.4, 3.0, 3.6, 2.8])
    errors = np.asarray([0.25, 0.35, 0.2, 0.3])
    ax.bar(
        x,
        values,
        yerr=errors,
        color=["#4677c8", "#6d5bd0", "#a64cb2", "#d14a78"],
        ecolor="#ff5b55",
        capsize=7,
        error_kw={"elinewidth": 3},
    )
    ax.set_xticks(x, ["control", "alpha", "beta", "gamma"])
    ax.set_ylim(0, 4.8)
    ax.set_xlabel("Sample group", rotation=14, labelpad=12)
    ax.set_ylabel("Measured response")
    ax.text(
        0.04,
        0.92,
        "notes stay visible",
        transform=ax.transAxes,
        fontsize=12,
    )
    ax.annotate(
        "peak",
        xy=(2, values[2] + errors[2]),
        xytext=(2.55, 4.35),
        arrowprops={"arrowstyle": "->", "color": "white"},
    )
    fig.savefig(Path(destination), dpi=100)
    plt.close(fig)
