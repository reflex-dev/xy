import pathlib
import tempfile

import numpy as np

import xy.pyplot as plt

x = np.linspace(0, 10, 200)
(line,) = plt.plot(x, np.sin(x))
tmpdir = tempfile.TemporaryDirectory()
before_png = pathlib.Path(tmpdir.name) / "before.png"
plt.savefig(before_png)
line.set_data(x, np.cos(x))
line.set_color("tab:red")
after_png = pathlib.Path(tmpdir.name) / "after.png"
plt.savefig(after_png)
