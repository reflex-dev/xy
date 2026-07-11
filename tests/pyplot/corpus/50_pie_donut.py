import xy.pyplot as plt

fig, axes = plt.subplots(1, 2, figsize=(8, 4))
axes[0].pie([2, 3, 5], labels=["A", "B", "C"], autopct="%.0f%%", startangle=90)
axes[1].pie(
    [4, 2, 3, 1],
    labels=["north", "east", "south", "west"],
    explode=[0, 0.08, 0, 0],
    wedgeprops={"width": 0.35, "edgecolor": "white"},
)
