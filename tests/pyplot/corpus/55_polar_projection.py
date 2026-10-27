import numpy as np

import xy.pyplot as plt

theta = np.linspace(0.0, 2.0 * np.pi, 17)
radius = 0.6 + 0.3 * np.cos(4.0 * theta)

fig, axes = plt.subplots(
    1,
    2,
    figsize=(8, 4),
    subplot_kw={"projection": "polar"},
)

axes[0].plot(theta, radius, color="tab:blue", label="response")
axes[0].fill(theta, radius, color="tab:blue", alpha=0.2)
axes[0].scatter(theta[::2], radius[::2], color="tab:orange", s=24)
axes[0].set_theta_zero_location("N")
axes[0].set_theta_direction(-1)
axes[0].set_thetagrids([0, 90, 180, 270], ["N", "E", "S", "W"])
axes[0].set_rlim(0.0, 1.0)
axes[0].set_rticks([0.25, 0.5, 0.75, 1.0])
axes[0].legend()

directions = np.arange(0.0, 2.0 * np.pi, np.pi / 4.0)
axes[1].bar(
    directions,
    [3, 5, 4, 7, 6, 4, 2, 3],
    width=np.pi / 5.0,
    bottom=1.0,
    color="tab:green",
    alpha=0.75,
)
axes[1].set_title("Polar bars")
