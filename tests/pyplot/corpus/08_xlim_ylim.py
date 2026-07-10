import numpy as np

import fastcharts.pyplot as plt

x = np.linspace(-5, 5, 200)
plt.plot(x, np.tanh(x))
plt.xlim(-3, 3)
plt.ylim(-1.5, 1.5)
