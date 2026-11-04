"""Shared date units refresh panels cached before a temporal fill was added."""

from datetime import datetime, timedelta

import numpy as np

import xy.pyplot as plt

dates = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(7)]
upper = np.array([3.0, 4.0, 5.0, 4.0, 6.0, 5.0, 7.0])
masked_dates = np.ma.masked_array(dates, mask=[False, False, False, True, False, False, False])
fig, axes = plt.subplots(2, 1, sharex=True, figsize=(7, 6))
axes[1].axhline(1, color="purple")
# Render before adding dates to exercise shared-axis cache refresh.
fig.canvas.draw()
axes[0].fill_between(masked_dates, upper, alpha=0.35)
axes[0].set_title("Shared dates: labels on the panel without date data")
