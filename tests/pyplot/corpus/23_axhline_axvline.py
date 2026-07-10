import numpy as np

import xy.pyplot as plt

x = np.linspace(0, 4, 80)
plt.plot(x, np.exp(-x) * np.cos(6 * x))
plt.axhline(0, color="k", linewidth=0.5)
plt.axvline(1.0, color="tab:red", linestyle="--")
