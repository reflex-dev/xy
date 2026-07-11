import numpy as np

import xy.pyplot as plt

rng = np.random.default_rng(7)
fig, axs = plt.subplots(2, 3)
axs[0, 0].boxplot([rng.normal(size=100), rng.normal(1, 2, size=100)])
axs[0, 1].violinplot([rng.normal(size=100), rng.normal(1, 2, size=100)])
axs[0, 2].errorbar([0, 1, 2], [2, 1, 3], yerr=[0.2, 0.1, 0.3])
axs[1, 0].hexbin(rng.normal(size=1000), rng.normal(size=1000))
axs[1, 1].ecdf(rng.normal(size=1000))
axs[1, 2].hist2d(rng.normal(size=1000), rng.normal(size=1000), bins=20)
