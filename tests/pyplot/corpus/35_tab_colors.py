import fastcharts.pyplot as plt

for i, name in enumerate(["tab:blue", "tab:orange", "tab:green", "tab:red", "tab:purple"]):
    plt.plot([0, 1], [i, i + 0.5], color=name, label=name)
plt.legend()
