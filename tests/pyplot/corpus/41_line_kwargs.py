import numpy as np

import fastcharts.pyplot as plt

x = np.arange(12)
plt.plot(
    x,
    np.sqrt(x),
    linestyle=":",
    linewidth=2,
    marker="s",
    markersize=4,
    alpha=0.9,
    color="m",
    label="root",
)
plt.legend()
