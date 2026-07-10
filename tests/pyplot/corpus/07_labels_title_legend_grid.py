import numpy as np

import fastcharts.pyplot as plt

x = np.linspace(0, 10, 100)
fig, ax = plt.subplots()
ax.plot(x, np.sin(x), label="sin")
ax.plot(x, np.cos(x), label="cos")
ax.set_xlabel("time [s]")
ax.set_ylabel("amplitude")
ax.set_title("Waves")
ax.legend()
ax.grid(True)
