import numpy as np

import xy.pyplot as plt

x = np.arange(5)
plt.stackplot(x, [1, 2, 3, 2, 1], [2, 1, 1, 2, 3], labels=["a", "b"])
plt.legend()
