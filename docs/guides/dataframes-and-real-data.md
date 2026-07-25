---
title: DataFrames and Real Data
description: Clean, aggregate, chart, and export a pandas DataFrame with public XY APIs.
---

# DataFrames and Real Data

XY accepts a pandas DataFrame anywhere its public mark API accepts `data=`.
Column-name strings then resolve against that table. Keep cleaning, joins,
grouping, and business calculations in the dataframe library; give XY the
finished columns that should become marks.

The workflow below is a complete script. It reads CSV data, validates the
important fields, aggregates duplicate daily rows, builds one line per
channel, and writes both interactive and static output. The embedded CSV keeps
the example copyable; replace `StringIO(SAMPLE)` with
`pd.read_csv("daily_metrics.csv", parse_dates=["day"])` for a real file.

Install pandas beside the released core package first:

~~~bash
python -m pip install xy pandas
~~~

## End-to-end example

~~~python
from io import StringIO
from pathlib import Path

import pandas as pd
import xy

SAMPLE = """day,channel,revenue,orders
2026-07-01,direct,1240.50,31
2026-07-01,partner,860.00,18
2026-07-02,direct,1385.00,34
2026-07-02,partner,940.25,21
2026-07-03,direct,1495.75,37
2026-07-03,partner,1015.00,22
2026-07-03,partner,125.00,3
2026-07-04,direct,,35
2026-07-04,partner,1120.50,25
"""

# For production, replace this with:
# raw = pd.read_csv("daily_metrics.csv", parse_dates=["day"])
raw = pd.read_csv(StringIO(SAMPLE), parse_dates=["day"])

required = {"day", "channel", "revenue", "orders"}
missing = required.difference(raw.columns)
if missing:
    raise ValueError(f"missing required columns: {sorted(missing)}")

clean = raw.assign(
    channel=raw["channel"].astype("string").str.strip(),
    revenue=pd.to_numeric(raw["revenue"], errors="coerce"),
    orders=pd.to_numeric(raw["orders"], errors="coerce"),
).dropna(subset=["day", "channel", "revenue"])

daily = (
    clean.groupby(["day", "channel"], as_index=False, observed=True)
    .agg(revenue=("revenue", "sum"), orders=("orders", "sum"))
    .sort_values(["channel", "day"])
)

palette = {"direct": "#2563eb", "partner": "#16a34a"}
lines = []
for channel, rows in daily.groupby("channel", sort=True, observed=True):
    lines.append(
        xy.line(
            x="day",
            y="revenue",
            data=rows,
            name=str(channel),
            color=palette.get(str(channel), "#6b7280"),
        )
    )

chart = xy.line_chart(
    *lines,
    xy.x_axis(label="day"),
    xy.y_axis(label="revenue (USD)"),
    xy.legend(),
    title="Daily revenue by channel",
    width=900,
    height=420,
)

output = Path("build")
output.mkdir(exist_ok=True)
chart.to_html(output / "daily-revenue.html")
chart.to_png(str(output / "daily-revenue.png"), width=1200, height=630)

print(daily)
print("wrote", output / "daily-revenue.html")
print("wrote", output / "daily-revenue.png")
~~~

Run it as a script, then open `build/daily-revenue.html`. In a notebook, leave
`chart` as the last expression in a cell instead of exporting it.

The example groups explicitly because `xy.line(...)` draws one ordered series;
it does not silently interpret a categorical column as multiple lines. Doing
the transformation first also makes row ordering, missing-value handling, and
aggregation reviewable outside the renderer.

## A single-table encoding

When one mark uses the whole table, pass the DataFrame once and refer to its
columns by name:

~~~python
scatter = xy.scatter_chart(
    xy.scatter(
        x="orders",
        y="revenue",
        color="channel",
        size=8,
        data=daily,
    ),
    xy.x_axis(label="orders"),
    xy.y_axis(label="revenue (USD)"),
    xy.legend(),
    title="Order value by channel and day",
)
~~~

The `color="channel"` string is a column mapping because `channel` is not a
CSS color. A value such as `color="#2563eb"` is a constant color. Keeping this
distinction explicit prevents a misspelled column from becoming an unintended
style.

## Mappings, Arrow, and Polars

You do not need pandas when a simpler boundary is clearer:

- **Mappings:** A dictionary of aligned one-dimensional columns works with the
  same `data=` and column-name pattern. It is a useful dependency-free boundary
  for application code.
- **PyArrow:** Install `pyarrow` separately and pass compatible Arrow Arrays or
  ChunkedArrays directly. Primitive, null-free float64 layouts have the best
  chance of avoiding a copy; nulls, chunks, integer or temporal conversion,
  and unsupported coordinate types can require materialization or rejection.
  See [Data and columns](/docs/xy/core-concepts/data/) for the exact boundary.
- **Polars:** XY does not currently document a dedicated Polars DataFrame
  contract. Extract supported one-dimensional columns explicitly, for example
  `frame["x"].to_numpy()` and `frame["y"].to_numpy()`, then pass those arrays
  to a mark. Converting to pandas is also an application-level option when the
  extra dependency and copy are acceptable.
- **SQL and DuckDB:** Execute filtering and aggregation in the query engine,
  then materialize only the result columns as pandas, Arrow, or NumPy values.
  XY does not execute SQL or manage an out-of-core query plan.

## Production data checklist

- Sort every ordered series before calling `xy.line`.
- Make numeric conversion and missing-value policy explicit; do not rely on a
  renderer to repair business data.
- Keep x, y, color, and size columns aligned after filtering.
- Test category cardinality and datetime precision with production-like data.
- Use `chart.memory_report()` when ingest copies or retained source size
  matter.
- Export a representative result in CI so a data-schema change fails before
  deployment.

Continue with [Large data and performance](/docs/xy/core-concepts/large-data-and-performance/),
[Display and export](/docs/xy/guides/display-and-export/), or
[Troubleshooting](/docs/xy/guides/troubleshooting/).
