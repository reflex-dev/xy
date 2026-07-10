import numpy as np

import xy.pyplot as plt

fig, ax = plt.subplots(figsize=(10, 3))
x = np.linspace(0, 100, 500)
ax.plot(x, np.cumsum(np.sin(x)))
ax.set_title("wide timeseries")
