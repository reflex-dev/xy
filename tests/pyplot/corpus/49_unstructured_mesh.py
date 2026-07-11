import numpy as np

import xy.pyplot as plt

x = np.array([0.0, 1.0, 0.0, 1.0, 0.5])
y = np.array([0.0, 0.0, 1.0, 1.0, 0.5])
z = np.sin(x * 3.0) + np.cos(y * 4.0)
triangles = np.array([[0, 1, 4], [1, 3, 4], [3, 2, 4], [2, 0, 4]])

fig, axes = plt.subplots(1, 3, figsize=(10, 3))
axes[0].tripcolor(x, y, z, triangles=triangles, cmap="viridis")
axes[1].triplot(x, y, "k-", triangles=triangles)
axes[1].tricontour(x, y, z, triangles=triangles, levels=4)
axes[2].tricontourf(x, y, z, triangles=triangles, levels=5, cmap="plasma")
