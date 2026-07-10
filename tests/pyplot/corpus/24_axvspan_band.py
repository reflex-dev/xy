import numpy as np

import xy.pyplot as plt

x = np.linspace(0, 24, 200)
plt.plot(x, 20 + 5 * np.sin(x / 24 * 2 * np.pi))
plt.axvspan(9, 17, alpha=0.2, color="tab:olive")
plt.axhspan(18, 22, alpha=0.1, color="0.5")
plt.xlabel("hour")
