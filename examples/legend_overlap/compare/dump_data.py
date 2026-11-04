"""Re-run the xy case generators' data paths and dump identical series to JSON."""

import json
import sys

import numpy as np

months = np.arange(12)


def fresh():
    return np.random.default_rng(7)


def growth(rng, start, slope, noise=4):
    return start + slope * months + rng.normal(0, noise, 12).cumsum() * 0.3


out = {}
rng = fresh()
out["1_rising_lines"] = {
    n: growth(rng, s, k).tolist()
    for n, s, k in [("Revenue", 40, 9), ("Gross profit", 30, 7), ("Net income", 20, 5)]
}
rng = fresh()
regions = ["North", "South", "East", "West", "Central", "Online", "Wholesale", "Partners"]
out["2_many_series"] = {
    r: growth(rng, 30 + 6 * i, 2 + i * 0.6).tolist() for i, r in enumerate(regions)
}
rng = fresh()
names = [
    "Monthly recurring revenue (USD)",
    "Customer acquisition cost (USD)",
    "Average contract value (USD)",
]
out["3_long_names"] = {n: growth(rng, 40 - 8 * i, 6 - i).tolist() for i, n in enumerate(names)}
rng = fresh()
out["4_stacked_area"] = {
    n: (lvl + rng.normal(0, 3, 12)).tolist()
    for n, lvl in [("Desktop", 40), ("Mobile", 35), ("Tablet", 15)]
}
out["5_grouped_columns"] = {
    "2024": [54, 65, 77, 86],
    "2025": [60, 72, 85, 96],
    "2026": [63, 76, 89, 101],
}
rng = fresh()
out["6_small_card"] = {
    n: growth(rng, s, k).tolist()
    for n, s, k in [("Signups", 40, 9), ("Activations", 35, 8), ("Paid conversions", 25, 6)]
}
with open(sys.argv[1], "w") as fh:
    json.dump(out, fh, indent=1)
