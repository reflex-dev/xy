"""A FastAPI app that serves xy charts.

Routes:

* ``GET /`` — an index of the gallery charts, each in an iframe with a "Code"
  panel showing the builder's source via :func:`inspect.getsource`.
* ``GET /chart/{id}`` — one ``charts.py`` builder rendered to a standalone HTML
  document with ``chart.to_html()``; interaction resolves in the browser.
* ``GET /drilldown`` — a 100M-point scatter whose density surface refines into
  exact points on zoom, using ``POST /api/xy/drilldown`` (a Starlette endpoint
  in ``live_drilldown.py``) for the view round-trips.

Run from ``examples/fastapi``::

    uv run uvicorn app:app --reload    # open http://127.0.0.1:8000

``XY_LIVE_POINTS`` sets the drilldown demo's point count.
"""

from __future__ import annotations

import html
import inspect
import threading
from collections.abc import Callable

import charts
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from live_drilldown import (
    LIVE_DRILLDOWN_ROUTE,
    LIVE_SCATTER_POINTS,
    drilldown_endpoint,
    live_drilldown_html,
)

app = FastAPI(title="xy × FastAPI")


# --- chart rendering --------------------------------------------------------


_html_cache: dict[str, str] = {}
_html_locks: dict[str, threading.Lock] = {}
_html_locks_guard = threading.Lock()


def _chart_html(chart_id: str) -> str:
    """Render one gallery chart to a standalone HTML document, once per id.

    Cached so repeat loads are instant. FastAPI runs sync routes in a
    threadpool, so a per-id lock keeps concurrent first requests for the same
    chart from each building its payload (the 10M density scatter would
    otherwise duplicate a large allocation).
    """
    cached = _html_cache.get(chart_id)
    if cached is not None:
        return cached
    with _html_locks_guard:
        lock = _html_locks.setdefault(chart_id, threading.Lock())
    with lock:
        if chart_id not in _html_cache:
            _html_cache[chart_id] = charts.BY_ID[chart_id].builder().to_html()
        return _html_cache[chart_id]


@app.get("/chart/{chart_id}", response_class=HTMLResponse)
def chart_html(chart_id: str) -> HTMLResponse:
    """Serve a live-generated standalone chart document."""
    if chart_id not in charts.BY_ID:
        # Do not echo the raw id into an HTML response (reflected-XSS sink);
        # HTTPException renders a JSON error instead.
        raise HTTPException(status_code=404, detail="unknown chart")
    return HTMLResponse(_chart_html(chart_id))


@app.get("/drilldown", response_class=HTMLResponse)
def drilldown_page() -> HTMLResponse:
    """Serve the live 100M-point drilldown chart (calls back to the app)."""
    return HTMLResponse(live_drilldown_html())


# The drilldown chart POSTs view windows here and gets back exact points or a
# refined density grid as raw f32 buffers. It is an ordinary Starlette endpoint
# (FastAPI is Starlette underneath), so mounting it is one line.
app.add_route(LIVE_DRILLDOWN_ROUTE, drilldown_endpoint, methods=["POST"])


@app.get("/env.json")
def env_json() -> JSONResponse:
    """The bundled chart client probes for a backend base URL; same-origin here."""
    return JSONResponse({})


# --- introspection: show the code that produced each chart ------------------

_POINT_LABEL = (
    f"{LIVE_SCATTER_POINTS // 1_000_000}M"
    if LIVE_SCATTER_POINTS % 1_000_000 == 0
    else f"{LIVE_SCATTER_POINTS:,}"
)


def _source(obj: Callable[..., object]) -> str:
    """The source of ``obj``, for the on-page code panel."""
    return inspect.getsource(obj)


@app.get("/code/{chart_id}", response_class=PlainTextResponse)
def chart_code(chart_id: str) -> PlainTextResponse:
    """The builder source for one chart (also inlined in the index accordion)."""
    info = charts.BY_ID.get(chart_id)
    if info is None:
        raise HTTPException(status_code=404, detail="unknown chart")
    return PlainTextResponse(_source(info.builder))


# --- page shell -------------------------------------------------------------

_STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2rem 1.25rem 4rem;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif;
  background: #f3f6fa; color: #101828;
}
main { max-width: 1120px; margin: 0 auto; }
header h1 { font-size: 1.9rem; margin: 0 0 .35rem; }
header p { color: #475467; margin: 0 0 1.5rem; max-width: 62ch; }
nav { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: 2rem; }
nav a {
  padding: .4rem .6rem; border: 1px solid #ccd6e2; border-radius: 8px;
  background: #fff; color: #1d2939; text-decoration: none; font-size: .84rem;
}
nav a:hover { border-color: #2563eb; color: #2563eb; }
.card {
  border: 1px solid #dde3ea; border-radius: 12px; background: #fbfcfe;
  overflow: hidden; margin-bottom: 1.5rem;
}
.card-head { padding: 1rem 1.15rem; }
.card-head h2 { font-size: 1.15rem; margin: 0; }
.card-head p { color: #667085; font-size: .88rem; margin: .3rem 0 0; }
.card iframe { display: block; width: 100%; height: 462px; border: 0; border-top: 1px solid #dde3ea; background: #fff; }
details { border-top: 1px solid #dde3ea; background: #fff; }
summary { cursor: pointer; padding: .8rem 1.15rem; font-weight: 700; font-size: .85rem; color: #1d2939; list-style: none; }
summary::-webkit-details-marker { display: none; }
summary::before { content: "› "; color: #98a2b3; }
details[open] summary::before { content: "⌄ "; }
pre {
  margin: 0; padding: 1.1rem 1.25rem; overflow-x: auto;
  background: #0b1120; color: #e5e7eb; font-size: .78rem; line-height: 1.55;
  border-top: 1px solid rgba(148,163,184,.2);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
.badge {
  display: inline-block; padding: .15rem .5rem; border-radius: 999px;
  background: #e0edff; color: #1d4ed8; font-size: .72rem; font-weight: 700;
  vertical-align: middle; margin-left: .5rem;
}
@media (prefers-color-scheme: dark) {
  body { background: #0b1120; color: #e5e7eb; }
  .card { background: #111a2e; border-color: #24304a; }
  nav a { background: #111a2e; border-color: #33415c; color: #cbd5e1; }
  nav a:hover { border-color: #60a5fa; color: #93c5fd; }
  .card-head p, header p { color: #94a3b8; }
  details, .card iframe { background: #0f1729; border-color: #24304a; }
  summary { color: #e5e7eb; }
  .badge { background: #1e293b; color: #93c5fd; }
}
"""


def _code_block(source: str) -> str:
    return f"<pre><code>{html.escape(source)}</code></pre>"


def _accordion(label: str, source: str) -> str:
    return f"<details><summary>{html.escape(label)}</summary>{_code_block(source)}</details>"


def _card(*, anchor: str, title: str, subtitle: str, iframe_src: str, code: str) -> str:
    return f"""
<section class="card" id="{anchor}">
  <div class="card-head">
    <h2>{html.escape(title)}</h2>
    <p>{html.escape(subtitle)}</p>
  </div>
  <iframe src="{iframe_src}" title="{html.escape(title)}" loading="lazy"></iframe>
  {_accordion("Code", code)}
</section>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    nav_links = "".join(
        f'<a href="#{info.id}">{html.escape(info.title)}</a>' for info in charts.GALLERY
    )
    nav_links += '<a href="#live-drilldown">Live drilldown</a>'

    gallery_cards = "".join(
        _card(
            anchor=info.id,
            title=info.title,
            subtitle=info.subtitle,
            iframe_src=f"/chart/{info.id}",
            code=_source(info.builder),
        )
        for info in charts.GALLERY
    )

    # The drilldown card shows both halves of the pattern: the page builder and
    # the server endpoint it calls back into.
    drilldown_code = (
        "# app.py — mount the callback route on the FastAPI app\n"
        + _source(drilldown_page).rstrip()
        + "\n\n"
        + 'app.add_route(LIVE_DRILLDOWN_ROUTE, drilldown_endpoint, methods=["POST"])\n\n'
        + "# live_drilldown.py — the endpoint that answers view windows\n"
        + _source(drilldown_endpoint)
    )
    drilldown_card = f"""
<section class="card" id="live-drilldown">
  <div class="card-head">
    <h2>Live {html.escape(_POINT_LABEL)} drilldown scatter <span class="badge">server tier</span></h2>
    <p>A {html.escape(_POINT_LABEL)}-point source rendered as a density surface that refines into
       exact points as you zoom, by calling back to <code>POST {html.escape(LIVE_DRILLDOWN_ROUTE)}</code>.</p>
  </div>
  <iframe src="/drilldown" title="Live drilldown" loading="lazy"></iframe>
  {_accordion("Code", drilldown_code)}
</section>
"""

    how_it_works = _accordion(
        "Code",
        _source(_chart_html) + "\n\n" + _source(chart_html),
    )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>xy × FastAPI</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
  <header>
    <h1>xy × FastAPI</h1>
    <p>Interactive WebGL2 charts served from a plain FastAPI app — no Reflex, no
       committed HTML. Each chart is generated on request with
       <code>chart.to_html()</code>; expand a card's <b>Code</b> panel to read the
       exact builder, loaded live from the server module.</p>
  </header>
  <nav>{nav_links}</nav>
  <section class="card" id="how-it-works">
    <div class="card-head">
      <h2>How it works</h2>
      <p>The whole app is one <code>charts.py</code> of builder functions plus a
         handful of FastAPI routes. Everything you see below is live-generated.</p>
    </div>
    {how_it_works}
  </section>
  {gallery_cards}
  {drilldown_card}
</main>
</body>
</html>"""
    return HTMLResponse(page)


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.get("/favicon.ico")
def favicon() -> RedirectResponse:
    return RedirectResponse(url="data:,", status_code=307)
