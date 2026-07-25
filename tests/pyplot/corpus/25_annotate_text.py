import numpy as np

import xy.pyplot as plt

x = np.linspace(0, 2 * np.pi, 100)
y = np.sin(x)
fig, ax = plt.subplots()
ax.plot(x, y)
ax.annotate("peak", xy=(np.pi / 2, 1.0), xytext=(2.5, 1.2), arrowprops=dict(arrowstyle="->"))
ax.text(4.0, -0.5, "trough region", fontsize=9, ha="center", color="tab:gray")
