import pathlib
import tempfile

import xy.pyplot as plt

fig, ax = plt.subplots()
ax.plot([0, 1, 2, 3], [10, 20, 15, 30], marker="o")
tmpdir = tempfile.TemporaryDirectory()
out_html = pathlib.Path(tmpdir.name) / "report.html"
fig.savefig(out_html)
