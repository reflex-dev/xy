import numpy as np

import fastcharts.pyplot as plt

rng = np.random.default_rng(7)
x = rng.random(40)
y = rng.random(40)
sizes = 300 * rng.random(40)
plt.scatter(x, y, s=sizes, c="tab:purple", alpha=0.5)
