import numpy as np

import fastcharts.pyplot as plt

x = np.linspace(0, 10, 100)
plt.plot(x, np.sin(x), color="0.5")
plt.plot(x, np.sin(x) + 1, color="0.8", linestyle="--")
plt.axhline(0.5, color="0.2", linewidth=0.8)
