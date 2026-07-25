import numpy as np

import xy.pyplot as plt

fig, axes = plt.subplots(2, 2, figsize=(8, 6))
axes[0, 0].loglog([1, 10, 100], [1, 5, 50], "o-")
axes[0, 1].hlines([1, 2, 3], 0, [1, 2, 3])
axes[0, 1].vlines([1, 2, 3], 0, [3, 2, 1])
axes[1, 0].broken_barh([(1, 2), (4, 1.5), (7, 2)], (2, 0.8))
axes[1, 0].fill_betweenx([0, 1, 2, 3], [0, 0.5, 0.2, 0.8], 1.5, alpha=0.3)
axes[1, 1].spy(np.eye(12) + np.eye(12, k=3))
