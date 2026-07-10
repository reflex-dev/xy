import numpy as np

import xy.pyplot as plt

z = np.random.default_rng(0).random((16, 16))
plt.imshow(z, cmap="plasma", vmin=0.0, vmax=1.0)
plt.title("noise field")
plt.colorbar()
