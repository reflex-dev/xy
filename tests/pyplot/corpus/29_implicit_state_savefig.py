import pathlib
import tempfile

import numpy as np

import xy.pyplot as plt

x = np.linspace(0, 2 * np.pi, 100)
plt.plot(x, np.sin(x))
plt.title("sine, saved")
tmpdir = tempfile.TemporaryDirectory()
out_png = pathlib.Path(tmpdir.name) / "sine.png"
plt.savefig(out_png)
