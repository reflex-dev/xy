"""pandas datetime-indexed Series/DataFrame plots keep calendar x coordinates."""

import pathlib
import tempfile

import numpy as np
import pandas as pd

import xy.pyplot as plt

daily = pd.Series(
    np.linspace(4000.0, 5000.0, 120),
    index=pd.date_range("2012-01-01", periods=120, freq="D"),
)
monthly = pd.DataFrame(
    {"north": np.linspace(1.0, 3.0, 24), "south": np.linspace(3.0, 1.0, 24)},
    index=pd.date_range("2012-01-01", periods=24, freq="MS"),
)
hourly = pd.Series(
    np.sin(np.linspace(0.0, 6.0, 72)),
    index=pd.date_range("2012-01-01", periods=72, freq="h"),
)

fig, axes = plt.subplots(1, 3, figsize=(14, 4))
daily.plot(ax=axes[0], title="Daily Series")
monthly.plot(ax=axes[1], title="Monthly DataFrame")
hourly.plot(ax=axes[2], title="Hourly Series")

tmpdir = tempfile.TemporaryDirectory()
out_png = pathlib.Path(tmpdir.name) / "pandas-dates.png"
fig.savefig(out_png)
