import numpy as np

import xy.pyplot as plt

rng = np.random.default_rng(11)
fig, axs = plt.subplots(2, 2, figsize=(8, 6))
x = np.linspace(0, 5, 60)
axs[0, 0].plot(x, np.sin(x))
axs[0, 0].set_title("line")
axs[0, 1].scatter(rng.random(30), rng.random(30), c="C3")
axs[0, 1].set_title("scatter")
axs[1, 0].bar(["a", "b", "c"], [3, 7, 2])
axs[1, 0].set_title("bar")
axs[1, 1].hist(rng.standard_normal(200), bins=15)
axs[1, 1].set_title("hist")
fig.suptitle("Four panels")
fig.tight_layout()
