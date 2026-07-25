import xy.pyplot as plt

fig, ax = plt.subplots()
ax.barh(["python", "rust", "go"], [70, 20, 10], color="tab:green")
ax.set_xlabel("share [%]")
