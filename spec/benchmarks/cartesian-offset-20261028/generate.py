import sys
from pathlib import Path

import xy

out = Path(sys.argv[1])
out.mkdir(exist_ok=True, parents=True)
offset = 1e12
f = xy.line_chart(
    xy.line(
        [offset + 100, offset + 900], [offset + 450] * 2, color="#0000ff", width=3, animation=False
    ),
    xy.scatter(
        [offset + 200, offset + 500, offset + 800],
        [offset + 200] * 3,
        color="#0000ff",
        size=8,
        animation=False,
    ),
    xy.area(
        [offset + 100, offset + 900],
        [offset - 100] * 2,
        base=[offset - 200] * 2,
        color="#0000ff",
        opacity=1,
        animation=False,
    ),
    xy.x_axis(domain=(offset, offset + 1000)),
    xy.y_axis(domain=(offset - 300, offset + 500)),
    xy.legend(show=False),
    xy.modebar(show=False),
    width=720,
    height=360,
).figure()
(out / "chart.html").write_text(f.to_html())
f.to_png(out / "native.png", scale=1)
