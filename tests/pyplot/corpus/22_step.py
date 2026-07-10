import numpy as np

import xy.pyplot as plt

x = np.arange(10)
y = np.array([1, 3, 2, 5, 4, 4, 6, 5, 7, 8])
plt.step(x, y, color="tab:red", linewidth=2)
