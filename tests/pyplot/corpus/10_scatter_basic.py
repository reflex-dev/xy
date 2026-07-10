import numpy as np

import fastcharts.pyplot as plt

rng = np.random.default_rng(42)
plt.scatter(rng.random(50), rng.random(50))
