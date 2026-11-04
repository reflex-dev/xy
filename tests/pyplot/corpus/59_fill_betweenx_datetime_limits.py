"""Date coordinates in fill_betweenx, and date view limits on either axis."""

from datetime import date, datetime, timedelta

import numpy as np

import xy.pyplot as plt

dates = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(7)]
levels = np.arange(7.0)
values = np.array([3.0, 4.0, 5.0, 4.0, 6.0, 5.0, 7.0])
fig, axes = plt.subplots(1, 3, figsize=(14, 4))
axes[0].fill_betweenx(levels, dates, dates[0], alpha=0.35)
axes[0].set_xlim(datetime(2025, 12, 31), datetime(2026, 1, 8))
axes[0].set_title("Date x extents, datetime limits")
axes[1].fill_betweenx(np.asarray(dates, dtype="datetime64[D]"), values, alpha=0.35)
axes[1].set_ylim(np.datetime64("2025-12-31"), np.datetime64("2026-01-10"))
axes[1].set_title("Date y extents, datetime64 limits")
axes[2].plot(dates, values)
axes[2].set_xlim(date(2025, 12, 30), date(2026, 1, 9))
axes[2].set_title("Line with date limits")
