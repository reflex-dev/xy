import numpy as np

import fastcharts.pyplot as plt

rng = np.random.default_rng(3)
plt.scatter(
    rng.random(25),
    rng.random(25),
    s=80,
    c="C2",
    edgecolors="black",
    linewidths=0.5,
    label="samples",
)
plt.legend()
