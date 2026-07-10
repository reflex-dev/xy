import numpy as np

import fastcharts.pyplot as plt

samples = np.random.default_rng(5).exponential(scale=2.0, size=400)
plt.hist(samples, bins=25, cumulative=True, density=True)
plt.title("empirical CDF")
