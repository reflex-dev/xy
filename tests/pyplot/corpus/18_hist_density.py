import numpy as np

import fastcharts.pyplot as plt

rng = np.random.default_rng(2)
plt.hist(rng.standard_normal(1000), bins=40, density=True, alpha=0.75, color="tab:orange")
