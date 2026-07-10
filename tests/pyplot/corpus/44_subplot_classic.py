import numpy as np

import fastcharts.pyplot as plt

x = np.linspace(0, 3, 60)
ax_top = plt.subplot(2, 1, 1)
ax_top.plot(x, np.sin(2 * np.pi * x))
ax_top.set_title("top")
ax_bottom = plt.subplot(2, 1, 2)
ax_bottom.plot(x, np.cos(2 * np.pi * x), "r--")
ax_bottom.set_title("bottom")
