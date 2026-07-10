import numpy as np

import fastcharts.pyplot as plt

plt.rcParams["figure.figsize"] = (12, 4)
plt.rcParams["lines.linewidth"] = 2.5
x = np.linspace(0, 50, 300)
plt.plot(x, np.sin(x) * np.exp(-x / 25))
plt.title("damped")
