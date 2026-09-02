"""Partial subplot grids, Artist-level keywords, legend proxies, and the bar
labeling idiom -- plain Matplotlib scripts that used to raise in the shim."""

import numpy as np

import xy.pyplot as plt

x = np.linspace(0, 2 * np.pi, 40)

# subplot(n, m, i) creates only cell i; the empty cells stay blank.
top_left = plt.subplot(221)
top_left.plot(x, np.sin(x), zorder=3, clip_on=False, rasterized=True, label="sin")
top_left.plot(x, np.cos(x), visible=False, label="_hidden")
top_left.legend(
    handles=[plt.Line2D([0], [0], color="C3", linestyle="--", label="fit")],
    loc=2,
)
top_left.grid(True, zorder=0)

bottom = plt.subplot(2, 1, 2)
bars = bottom.bar(["a", "b", "c"], [1, 2, 3], yerr=[0.1, 0.2, 0.3], tick_label=None)
for rect in bars:
    bottom.text(
        rect.get_x() + rect.get_width() / 2,
        rect.get_height(),
        f"{rect.get_height():g}",
        ha="center",
        alpha=0.8,
    )
bottom.scatter([0, 1, 2], [0.5, 1.5, 2.5], facecolors="none", edgecolors="k", zorder=4)
bottom.hlines(1.0, -0.5, 2.5, linestyle=":", colors=plt.cm.tab10(3))
bottom.legend(
    handles=[
        plt.Rectangle((0, 0), 1, 1, facecolor="C0", label="bars"),
        plt.Line2D([0], [0], color="k", marker="o", linestyle="none", label="points"),
    ],
    loc=(0.02, 0.6),
)
