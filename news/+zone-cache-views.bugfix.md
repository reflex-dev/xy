Charts over several disk-backed columns from one file (the rows of a 2-D
`np.memmap` table, or `np.memmap(offset=...)` columns packed into one file) no
longer reuse one column's cached statistics for another, which gave a column
the other column's axis range when the chart was built again.
