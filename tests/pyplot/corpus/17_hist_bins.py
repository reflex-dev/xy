import numpy as np

import fastcharts.pyplot as plt

data = np.random.default_rng(1).normal(loc=100, scale=15, size=500)
plt.hist(data, bins=30)
plt.xlabel("IQ")
