import numpy as np

import fastcharts.pyplot as plt

t = np.arange(0, 10, 0.5)
fig, ax1 = plt.subplots()
ax1.plot(t, np.exp(t / 5), color="tab:blue", label="growth")
ax1.set_ylabel("growth", color="tab:blue")
ax2 = ax1.twinx()
ax2.plot(t, np.sin(t), color="tab:red")
ax2.set_ylabel("oscillation", color="tab:red")
