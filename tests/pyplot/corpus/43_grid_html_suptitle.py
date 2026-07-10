import pathlib
import tempfile

import numpy as np

import xy.pyplot as plt

rng = np.random.default_rng(4)
fig, axs = plt.subplots(1, 2, figsize=(8, 3))
axs[0].plot(np.cumsum(rng.standard_normal(100)))
axs[1].hist(rng.standard_normal(300), bins=20)
fig.suptitle("Daily report")
tmpdir = tempfile.TemporaryDirectory()
out_html = pathlib.Path(tmpdir.name) / "grid.html"
fig.savefig(out_html)
