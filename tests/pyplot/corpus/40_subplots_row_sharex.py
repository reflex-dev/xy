import numpy as np

import fastcharts.pyplot as plt

x = np.linspace(0, 10, 100)
fig, axs = plt.subplots(1, 3, sharex=True, figsize=(9, 3))
for i, ax in enumerate(axs):
    ax.plot(x, np.sin(x + i))
    ax.set_title(f"phase {i}")
