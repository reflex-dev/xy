import numpy as np

import fastcharts.pyplot as plt

x = np.arange(10)
plt.plot(x, x * 1.5, "C1-.s")
plt.plot(x, x * 0.5, "C4:")
