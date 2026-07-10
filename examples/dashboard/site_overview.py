"""A site-overview dashboard built from fastcharts sparklines.

Card chrome is plain HTML/CSS; every metric sparkline is a real composed
fastcharts chart — chrome-hidden, edge-to-edge (`padding=...`), gradient area
fills, and smooth curves. The client bundle is embedded once and each chart
renders from its own spec + base64 blob into its card.

    uv run python examples/dashboard/site_overview.py       # writes site_overview.html
    uv run python examples/dashboard/site_overview.py --png  # also renders a PNG

Showcases: `fc.chart(..., padding=...)`, `curve="smooth"`,
`fill="linear-gradient(...)"`, `tick_label_strategy="none"`, and
`width="100%"` responsive sizing.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import numpy as np

import fastcharts as fc
from fastcharts.export import _STANDALONE_CSP, _bundled_js, _json_for_inline_script

HERE = Path(__file__).resolve().parent
BLUE, PURPLE, ORANGE = "#2f6bff", "#8b5cf6", "#f97316"


def spark(kind: str, x, y, color: str, *, fill: bool = True, width: float = 2.4):
    """A chrome-less, edge-to-edge sparkline -> (spec, base64 blob).

    `width="100%"` fills the (narrower) dashboard panel via the client's
    ResizeObserver rather than overflowing at a fixed pixel width.
    """
    if kind == "area":
        mark = fc.area(
            x,
            y,
            color=color,
            curve="smooth",
            line_width=width,
            line_opacity=1.0,
            fill="linear-gradient(currentColor, transparent)" if fill else None,
        )
    else:
        mark = fc.line(x, y, color=color, curve="smooth", width=width)
    hidden_axis = {
        "style": {"grid_color": "rgba(0,0,0,0)", "axis_color": "rgba(0,0,0,0)"},
        "tick_label_strategy": "none",
    }
    chart = fc.chart(
        mark,
        fc.x_axis(**hidden_axis),
        fc.y_axis(**hidden_axis),
        fc.legend(show=False),
        fc.tooltip(show=False),
        fc.modebar(show=False),
        width="100%",
        height=104,
        padding=[6, 1, 2, 1],
    )
    spec, blob = chart.figure().build_payload()
    return spec, base64.b64encode(blob).decode("ascii")


def _series():
    rng = np.random.default_rng(42)
    x = np.arange(90.0)
    dr = 69 + np.sin(np.linspace(0.4, 5.6, 90)) * 1.1 + rng.standard_normal(90) * 0.45
    rd = 590 + np.cumsum(np.abs(rng.standard_normal(90)) * 6 + np.linspace(0, 14, 90))
    tv = 40 + np.abs(rng.standard_normal(90)) * 25
    tv[78:] = np.linspace(120, 7800, 12)
    ot = np.clip(
        12000 + np.cumsum(rng.standard_normal(90) * 1400) + rng.standard_normal(90) * 2200,
        4400,
        20500,
    )
    ok = np.concatenate(
        [
            7100 + rng.standard_normal(30) * 120,
            np.linspace(7100, 900, 40) + rng.standard_normal(40) * 150,
            500 + rng.standard_normal(20) * 60,
        ]
    )
    return x, dr, rd, tv, ot, ok


CHECK = (
    '<svg viewBox="0 0 20 20" width="15" height="15"><circle cx="10" cy="10" r="10" fill="#f7941d"/>'
    '<path d="M6 10.5l2.5 2.5L14 7.5" fill="none" stroke="#fff" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
CARET = (
    '<svg viewBox="0 0 10 6" width="9" height="6"><path d="M0 0l5 6 5-6z" fill="#98a2b3"/></svg>'
)
STAR = (
    '<svg viewBox="0 0 20 20" width="17" height="17"><path d="M10 1l2.6 5.3 5.9.9-4.3 4.1 1 5.8L10 '
    '14.9 4.8 17l1-5.8L1.5 7.2l5.9-.9z" fill="none" stroke="#98a2b3" stroke-width="1.4"/></svg>'
)


def _metric(cid, title, value, delta, up, sub, y_hi, y_lo):
    cls, sign = ("up", "+") if up else ("down", "")
    sub_html = f'<div class="sub">{sub}</div>' if sub else '<div class="sub">&nbsp;</div>'
    return f"""
  <div class="panel metric">
    <div class="mtitle">{title}</div>
    <div class="mrow"><span class="mnum">{value}</span><span class="delta {cls}">{sign}{delta}</span></div>
    {sub_html}
    <div class="chartwrap">
      <div id="{cid}" class="chart"></div>
      <div class="yaxis"><span>{y_hi}</span><span>{y_lo}</span></div>
    </div>
  </div>"""


def _crawl(label, val, delta, up):
    cls, sign = ("up", "+") if up else ("down", "")
    return (
        f'<div class="crawl"><span class="ck">{label}</span>'
        f'<span class="cv">{val}<b class="delta {cls}">{sign}{delta}</b></span></div>'
    )


CSS = """
*{box-sizing:border-box}
body{margin:0;background:#eef1f5;font-family:'Inter',-apple-system,system-ui,'Segoe UI',sans-serif;padding:28px}
.dash{display:flex;background:#fff;border:1px solid #e6e9ef;border-radius:12px;box-shadow:0 1px 2px rgba(16,24,40,.06);overflow:hidden;max-width:1280px;margin:0 auto}
.panel{padding:16px 18px;border-right:1px solid #eef0f4;min-width:0}
.panel:last-child{border-right:none}
.site{flex:0 0 288px}
.metric{flex:1 1 0;display:flex;flex-direction:column}
.sitehead{display:flex;align-items:flex-start;gap:10px}
.thumb{width:34px;height:34px;border:1px solid #e6e9ef;border-radius:5px;padding:3px;flex:0 0 auto}
.tbar{height:4px;background:#6b7cff;border-radius:2px;margin-bottom:3px}
.tbody{display:flex;flex-wrap:wrap;gap:2px}
.tbody span{width:6px;height:6px;background:#e6e9ef;border-radius:1px}
.siteid{flex:1 1 auto;min-width:0}
.sname{display:flex;align-items:center;gap:5px;font-weight:600;font-size:15px;color:#101828}
.surl{display:flex;align-items:center;gap:5px;color:#667085;font-size:12.5px;margin-top:1px}
.actions{display:flex;align-items:center;gap:9px;font-size:12px;color:#667085}
.pill{border:1px solid #d0d5dd;border-radius:11px;padding:2px 9px;color:#475467}
.act{display:flex;align-items:center;gap:3px;white-space:nowrap}
.kebab{font-size:16px;line-height:1}
.health{margin-top:20px}.hlabel{color:#475467;font-size:13px;margin-bottom:6px}
.hrow{display:flex;align-items:center;gap:8px}
.hbadge{display:inline-flex;align-items:center;justify-content:center;width:40px;height:26px;background:#e7f7ec;color:#12a150;font-weight:700;font-size:15px;border-radius:13px}
.crawls{margin-top:18px;display:flex;flex-direction:column;gap:9px}
.crawl{display:flex;justify-content:space-between;font-size:13px}
.ck{color:#475467}.cv{color:#101828;font-weight:600;display:flex;gap:7px;align-items:baseline}
.showcomp{display:flex;align-items:center;gap:6px;margin-top:20px;color:#475467;font-size:13px}
.delta{font-size:12px;font-weight:600}.delta.up{color:#12a150}.delta.down{color:#e5484d}
.mtitle{color:#475467;font-size:13px}
.mrow{display:flex;align-items:baseline;gap:8px;margin-top:7px}
.mnum{font-size:30px;font-weight:700;color:#101828;letter-spacing:-.5px}
.sub{color:#98a2b3;font-size:11.5px;margin-top:3px;height:15px}
.chartwrap{position:relative;margin-top:14px;flex:1 1 auto;display:flex;align-items:flex-end;min-height:96px}
.chart{width:100%}
.yaxis{position:absolute;right:0;top:0;bottom:0;display:flex;flex-direction:column;justify-content:space-between;align-items:flex-end;color:#98a2b3;font-size:11px;pointer-events:none}
"""


def build_html() -> str:
    x, dr, rd, tv, ot, ok = _series()
    charts = [
        ("dr", spark("line", x, dr, PURPLE, fill=False, width=2.0)),
        ("rd", spark("area", x, rd, BLUE)),
        ("tv", spark("area", x, tv, ORANGE)),
        ("ot", spark("area", x, ot, ORANGE)),
        ("ok", spark("area", x, ok, ORANGE)),
    ]
    mounts = "\n".join(
        f'<script>fastcharts.renderStandalone(document.getElementById("{cid}"),'
        f"{_json_for_inline_script(spec)},"
        f'Uint8Array.from(atob("{b64}"),c=>c.charCodeAt(0)).buffer);</script>'
        for cid, (spec, b64) in charts
    )
    thumb = (
        '<div class="thumb"><div class="tbar"></div><div class="tbody">'
        + "".join("<span></span>" for _ in range(6))
        + "</div></div>"
    )
    body = f"""
<div class="dash">
  <div class="panel site">
    <div class="sitehead">
      {thumb}
      <div class="siteid">
        <div class="sname">Reflex {CHECK}</div>
        <div class="surl">*.reflex.dev/* {CARET}</div>
      </div>
      <div class="actions"><span class="pill">Basic</span>
        <span class="act">&#128101; Shared</span><span class="act">{STAR}</span>
        <span class="act kebab">&#8942;</span></div>
    </div>
    <div class="health"><div class="hlabel">Health Score</div>
      <div class="hrow"><span class="hbadge">85</span><span class="delta up">+35</span></div></div>
    <div class="crawls">
      {_crawl("Crawled", "1.2K", "1.2K", True)}{_crawl("Redirects", "5", "5", False)}
      {_crawl("Broken", "3", "2", False)}{_crawl("Blocked", "1", "1", False)}
    </div>
    <div class="showcomp">{CARET} Show competitors</div>
  </div>
  {_metric("dr", "Domain Rating", "71", "6", True, None, "100", "0")}
  {_metric("rd", "Referring domains", "1.7K", "1.1K", True, None, "1.6K", "591")}
  {_metric("tv", "Total visitors", "7.8K", "7.8K", True, "Avg. monthly: 651", "7.8K", "0")}
  {_metric("ot", "Organic traffic", "18.3K", "13.3K", True, "Value: $3.8K", "20.5K", "4.4K")}
  {_metric("ok", "Organic keywords", "541", "6.7K", False, None, "7.2K", "408")}
</div>
{mounts}"""
    return (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{_STANDALONE_CSP}">'
        f"<style>{CSS}</style></head><body>"
        f"<script>{_bundled_js('standalone')}</script>{body}</body></html>"
    )


def main() -> None:
    doc = build_html()
    out = HERE / "site_overview.html"
    out.write_text(doc, encoding="utf-8")
    print(f"wrote {out}")
    if "--png" in sys.argv:
        from fastcharts.export import html_to_png

        png = HERE / "site_overview.png"
        png.write_bytes(html_to_png(doc, 1336, 340))
        print(f"wrote {png}")


if __name__ == "__main__":
    main()
