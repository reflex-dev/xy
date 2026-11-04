"""Write sheet.html: every case with the default, "best" and "outside top" legend.

Run after make_cases.py and shoot.js, then screenshot sheet.html (shoot.js's
sibling `node examples/legend_overlap/shoot_sheet.js`) to refresh
contact_sheet.png.
"""

import html
import json
from pathlib import Path

HERE = Path(__file__).parent
CASES = [
    ("1_rising_lines", "Lines that rise into the top-right corner"),
    ("2_many_series", "8 series"),
    ("3_long_names", "Long series names"),
    ("4_stacked_area", "Stacked area (no empty corner)"),
    ("5_grouped_columns", "Grouped columns, tallest on the right"),
    ("6_small_card", "Small 320x200 card"),
    ("7_work_orders", "Reported builder chart: stacked bars at the axis maximum"),
]
VARIANTS = [
    ("default", "default (loc=None)"),
    ("best", 'loc="best"'),
    ("outside_top", 'loc="outside top"'),
]


def main() -> None:
    report = {
        row["file"].removesuffix(".html"): row["legend"]
        for row in json.loads((HERE / "report.json").read_text())
    }
    head = "".join(f"<th>{label}</th>" for _tag, label in VARIANTS)
    rows = []
    for key, title in CASES:
        cells = "".join(
            f'<td><div class=frame><img src="png/{key}__{tag}.png" alt="{html.escape(f"{title}, {label}")}"></div>'
            f"<div class=cap>resolved: {(report[f'{key}__{tag}'] or {}).get('loc', 'not rendered')}</div></td>"
            for tag, label in VARIANTS
        )
        rows.append(f"<tr><td colspan=3 class=case>{title}</td></tr><tr>{cells}</tr>")
    (HERE / "sheet.html").write_text(
        "<!doctype html><meta charset=utf-8><style>"
        "body{font:14px system-ui;margin:16px;background:#fff;color:#111}"
        "table{border-collapse:collapse}th{text-align:left;padding:4px 6px}"
        "td{padding:4px 6px;vertical-align:top}.case{font-weight:600;padding-top:14px}"
        ".frame{width:440px;height:230px;border:1px solid #ddd;display:flex;"
        "align-items:center;justify-content:center}"
        ".frame img{max-width:432px;max-height:222px}.cap{color:#555;font-size:12px}"
        "</style><h2 style='margin:0 0 6px'>Legend placement: default vs best vs outside top</h2>"
        f"<table><tr>{head}</tr>{''.join(rows)}</table>\n"
    )


if __name__ == "__main__":
    main()
