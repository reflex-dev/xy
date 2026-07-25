import xy.pyplot as plt

fruits = ["apple", "banana", "cherry", "date"]
counts = [12, 35, 8, 21]
plt.bar(fruits, counts, color="tab:blue")
plt.ylabel("count")
plt.title("Fruit inventory")
