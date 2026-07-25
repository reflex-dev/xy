import xy.pyplot as plt

labels = ["Q1", "Q2", "Q3", "Q4"]
product_a = [20, 34, 30, 35]
product_b = [25, 32, 34, 20]
plt.bar(labels, product_a, label="Product A")
plt.bar(labels, product_b, bottom=product_a, label="Product B")
plt.ylabel("revenue")
plt.legend()
