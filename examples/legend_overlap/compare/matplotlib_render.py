"""Render the same six cases with real matplotlib and its default ax.legend()."""

import json
import pathlib
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

root = pathlib.Path(sys.argv[1])
data = json.loads((root / "data.json").read_text())
(root / "matplotlib").mkdir(exist_ok=True)
for key, series in data.items():
    w, h = (3.2, 2.0) if key == "6_small_card" else (5.2, 3.0)
    fig, ax = plt.subplots(figsize=(w, h), dpi=200, layout="constrained")
    if key == "4_stacked_area":
        ax.stackplot(range(12), *series.values(), labels=list(series), alpha=0.6)
    elif key == "5_grouped_columns":
        x = np.arange(4)
        for i, (n, ys) in enumerate(series.items()):
            ax.bar(x + (i - 1) * 0.27, ys, 0.27, label=n)
        ax.set_xticks(x, ["Q1", "Q2", "Q3", "Q4"])
    else:
        for n, ys in series.items():
            ax.plot(range(12), ys, label=n)
    ax.legend()  # matplotlib default: loc="best"
    fig.savefig(root / "matplotlib" / f"{key}.png")
    plt.close(fig)
    print("wrote", key)
