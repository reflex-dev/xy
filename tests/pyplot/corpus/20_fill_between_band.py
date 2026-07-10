import numpy as np

import xy.pyplot as plt

x = np.linspace(0, 10, 100)
y = np.sin(x)
err = 0.2 + 0.1 * np.abs(np.cos(x))
fig, ax = plt.subplots()
ax.plot(x, y, "C0", label="mean")
ax.fill_between(x, y - err, y + err, color="C0", alpha=0.3, label="band")
ax.legend()
