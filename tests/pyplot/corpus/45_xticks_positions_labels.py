import numpy as np

import fastcharts.pyplot as plt

x = np.arange(10)
plt.plot(x, x**1.5)
plt.xticks([0, 2, 4, 6, 8], ["zero", "two", "four", "six", "eight"], rotation=30)
