import numpy as np

import fastcharts.pyplot as plt

t = np.arange(0.0, 5.0, 0.2)
plt.plot(t, t, "r--", t, t**2, "bs", t, t**3, "g^")
