"""Removing a temporal fill removes every region before numeric replacement."""

from datetime import datetime, timedelta

import numpy as np

import xy.pyplot as plt

dates = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(7)]
upper = np.array([3.0, 4.0, 5.0, 4.0, 6.0, 5.0, 7.0])
masked_dates = np.ma.masked_array(dates, mask=[False, False, False, True, False, False, False])
fig, ax = plt.subplots()
removed = ax.fill_between(masked_dates, upper)
fig.canvas.draw()
removed.remove()
ax.fill_between([0, 1, 2], [1, 2, 1], alpha=0.35)
# Matplotlib retains removed artists' data limits until explicitly reset.
ax.set_xlim(-0.1, 2.1)
ax.set_ylim(0, 3)
ax.set_title("All date regions removed: numeric replacement")
