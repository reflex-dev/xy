# reflex-xy demo

One page exercising the whole integration: a 1M-point drillable density
scatter, hover row readout, box-select cross-filtering a histogram, a live
streaming line — all chart data on the app's own websocket — plus a static
chart passed directly as a `xy.Chart` (compiled to a payload asset, no
backend involvement at all).

```bash
# from the xy repo root
uv venv && uv pip install -e ".[dev]" -e python/reflex-xy
cd python/reflex-xy/examples/demo_app
reflex run
```

Open the printed URL (usually http://localhost:3000). Zoom deep into the
cloud to watch density drill into exact points; hover them for f64 rows;
box-select to cross-filter the histogram; hit "go live" for the stream.

Headless verification of the transport claims (one shared websocket, binary
payloads, drill, hover loop, streaming) — with the app running:

```bash
python3 scripts/reflex_ws_smoke.py --frontend http://localhost:3000
```
