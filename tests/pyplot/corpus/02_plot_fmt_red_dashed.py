import numpy as np

import xy.pyplot as plt

fig, ax = plt.subplots()
x = np.linspace(0, 5, 50)
ax.plot(x, x**2, "r--")
ax.set_title("quadratic")
