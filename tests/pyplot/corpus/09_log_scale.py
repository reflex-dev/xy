import numpy as np

import fastcharts.pyplot as plt

x = np.logspace(0, 3, 30)
plt.plot(x, x**2)
plt.xscale("log")
plt.yscale("log")
plt.title("log-log")
