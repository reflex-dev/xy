import numpy as np

import fastcharts.pyplot as plt

rng = np.random.default_rng(0)
x = rng.random(100)
y = rng.random(100)
plt.scatter(x, y, c=x + y, cmap="viridis", alpha=0.6)
plt.colorbar()
