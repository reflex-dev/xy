import numpy as np

import xy.pyplot as plt

x, y = np.meshgrid(np.arange(5), np.arange(4))
u = np.cos(x)
v = np.sin(y)
fig, axs = plt.subplots(1, 3)
axs[0].quiver(x, y, u, v, angles="xy", scale_units="xy", scale=1)
axs[1].barbs(x, y, u, v)
axs[2].streamplot(np.arange(5), np.arange(4), u, v)
