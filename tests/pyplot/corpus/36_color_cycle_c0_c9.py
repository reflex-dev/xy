import numpy as np

import fastcharts.pyplot as plt

x = np.linspace(0, 1, 20)
for i in range(10):
    plt.plot(x, x * (i + 1), f"C{i}")
plt.title("full prop cycle")
