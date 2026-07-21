# reflex-xy demo

One page exercising the whole integration: a 1M-point drillable density
scatter, all four semantic Reflex events, box-select cross-filtering a
histogram, a live streaming line — all chart data on the app's own websocket
— plus a static chart passed directly as a `xy.Chart` (compiled to a payload
asset, no backend involvement at all).

```bash
# from the xy repo root
uv venv && uv pip install -e ".[dev]" -e python/reflex-xy
cd python/reflex-xy/examples/demo_app
reflex run
```

Open the printed URL (usually http://localhost:3000). Zoom deep into the
cloud to watch density drill into exact points; hover them for f64 rows;
box-select to cross-filter the histogram; hit "go live" for the stream.

## PR #113 interaction reproduction

The badges below the cloud are event counters. Every point click, completed
selection, and final pan/zoom updates Reflex state and deliberately republishes
the source chart; its title's `handler revision` confirms each republish.

1. Pan or zoom, then wait for the `view` badge to increment once. The chosen
   viewport must survive the title update, and the counter must stay put after
   that single increment.
2. Box-select a large area. The `select` readout shows the exact total, bounded
   JSON row/ID counts, `truncated`, and the complete server-resolved count. The
   histogram must cross-filter while the cloud keeps both its viewport and
   selection highlight. The selection counter must increment only once.
3. Click an exact point (zoom in if the cloud is still in its density tier).
   The `click` readout shows its canonical row ID, f64 data coordinates,
   canvas-relative coordinates, and active keyboard modifiers. The click
   counter must increment only once.
4. Focus a point and press Enter or Space. It must produce the same click
   readout contract as pointer activation.
5. Clear the selection. The histogram must return to all points and the select
   counter must increment exactly once again.

These checks reproduce the stable-token republish path and make viewport or
selection loss, stale event handling, and restore feedback loops visible.

Headless verification of the transport claims (one shared websocket, binary
payloads, drill, hover loop, streaming) — with the app running:

```bash
python3 scripts/reflex_ws_smoke.py --frontend http://localhost:3000
```
