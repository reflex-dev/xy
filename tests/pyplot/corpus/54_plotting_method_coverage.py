"""Direct calls for plotting methods that were previously covered only by family tests."""

import numpy as np

import xy.pyplot as plt

fig, axes = plt.subplots(5, 4, figsize=(12, 12))
axes = axes.ravel()
x = np.linspace(0.1, 2.0, 32)
y = np.sin(x)
z = np.arange(16.0).reshape(4, 4)

axes[0].semilogx(x, y)
axes[1].semilogy(x, x)
axes[2].stem(x[:5], y[:5])
axes[3].stairs([1, 3, 2], [0, 1, 2, 3])
axes[4].eventplot([[0.2, 0.5, 0.9], [0.1, 0.7]])
axes[5].fill([0, 1, 1], [0, 0, 1])
axes[6].arrow(0, 0, 1, 1)
axes[7].axline((0, 0), (1, 1))
axes[8].acorr(y, maxlags=8)
axes[9].angle_spectrum(y)
axes[10].csd(y, y * 0.5, NFFT=16)
axes[11].matshow(z)
axes[12].pcolor(z)
axes[13].pcolorfast(z)
axes[14].pcolormesh(z)
contours = axes[15].contour(z)
axes[15].clabel(contours)
axes[16].contourf(z)
q = axes[17].quiver([0], [0], [1], [1])
axes[17].quiverkey(q, 0.8, 0.9, 1, "1")
