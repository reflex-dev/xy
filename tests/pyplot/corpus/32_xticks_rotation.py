import fastcharts.pyplot as plt

months = ["January", "February", "March", "April", "May", "June"]
values = [3, 7, 4, 9, 2, 6]
plt.bar(months, values)
plt.xticks(rotation=45)
plt.ylabel("events")
