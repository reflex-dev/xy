import fastcharts.pyplot as plt

fig, ax = plt.subplots()
ax.bar(["alpha", "beta", "gamma"], [5, 3, 6])
ax.tick_params(axis="x", labelrotation=90)
