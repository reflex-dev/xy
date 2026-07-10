import fastcharts.pyplot as plt

plt.figure(1)
plt.plot([1, 2, 3])
plt.figure(2)
plt.plot([3, 2, 1], "r-")
plt.figure(1)
plt.title("back on figure one")
