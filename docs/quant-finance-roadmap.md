# Quant Finance Roadmap

This document is the API and implementation plan for making fastcharts a
production-grade quant finance charting surface. The goal is not to clone one
screen of TradingView. The goal is to support the same class of workflow:
high-performance OHLC rendering, composable studies, user-authored drawings,
forecasting/risk tools, volume tools, chart patterns, and application-level
customization through Python and Reflex-style components.

## Reference Surface

TradingView's drawing tools split the relevant finance surface into these
families:

| Family | Tools to cover | Product meaning |
|---|---|---|
| Chart patterns | XABCD, ABCD, triangle, three drives, head and shoulders, Elliott waves, cyclic lines, time cycles, sine line | Manual pattern markup first; optional detection later. |
| Forecasting | Long position, short position, position forecast, bars pattern, ghost feed, sector | Trade planning, scenario projection, and visual comparison to prior price action. |
| Volume based measures | Anchored VWAP, fixed range volume profile, anchored volume profile | Volume-weighted price and support/resistance analysis over anchored ranges. |
| Measurement | Price range, date range, date and price range | Fast readouts for price, percentage, bars, duration, and ticks. |
| Supporting tools | Magnet/snap, keep drawing, lock/hide drawings, visibility by interval, object tree/templates | The difference between demo drawings and a real trading workstation. |

Sources used for this plan:

- [TradingView drawing tools available](https://www.tradingview.com/support/solutions/43000703396-drawing-tools-available-on-tradingview/)
- [Long and short position calculations](https://www.tradingview.com/support/solutions/43000475660-how-to-use-long-and-short-position-drawing-tools/)
- [Position forecast drawing tool](https://www.tradingview.com/support/solutions/43000517004-position-forecast-drawing-tool/)
- [Bar pattern drawing tool](https://www.tradingview.com/support/solutions/43000517006-bar-pattern-drawing-tool/)
- [Ghost feed drawing tool](https://www.tradingview.com/support/solutions/43000748168-ghost-feed-drawing-tool/)
- [Sector drawing tool](https://www.tradingview.com/support/solutions/43000516995-sector-drawing-tool/)
- [Anchored VWAP drawing tool](https://www.tradingview.com/support/solutions/43000669764-anchored-vwap-drawing-tool/)
- [Fixed range volume profile](https://www.tradingview.com/support/solutions/43000707985-fixed-range-volume-profile-drawing-tool/)
- [Anchored volume profile](https://www.tradingview.com/support/solutions/43000707989-anchored-volume-profile-drawing-tool/)
- [XABCD pattern drawing tool](https://www.tradingview.com/support/solutions/43000569909-xabcd-pattern-drawing-tool/)
- [ABCD pattern drawing tool](https://www.tradingview.com/support/solutions/43000570202-abcd-pattern-drawing-tool/)

## Competitive Position

The finance goal is not just to add candlesticks. The goal is to become the
best Python-native foundation for high-performance, application-controlled
finance charts. The current branch is ahead of generic Python plotting
libraries in architecture and finance-overlay ambition, but it should not yet be
marketed as beating the whole finance charting ecosystem.

Honest current claim:

> FastCharts is building a TradingView-class finance surface from Python, backed
> by WebGL, binary transport, Rust/native kernels, composable finance layers, and
> Reflex-controlled state. The current finance branch already covers the core
> API shape and several advanced overlays, but finance-specific performance and
> product-maturity claims still need dedicated benchmarks and UX hardening.

Competitive read:

| Competitor | What they are strong at | FastCharts position |
|---|---|---|
| Plotly | Mature Python API, candlestick/OHLC traces, range slider, annotations, Dash ecosystem. | FastCharts should beat Plotly on large-data payload/rendering architecture, but not yet on docs, maturity, or finance UX breadth. |
| mplfinance | Purpose-built static financial charts, volume, moving averages, Renko, point-and-figure, and report/backtest workflows. | FastCharts should beat mplfinance for interactive WebGL finance apps; mplfinance remains stronger for mature static finance plotting. |
| Lightweight Charts Python | Trading-oriented browser UI, realtime updates, crosshair, drawings, subcharts, and TradingView-style behavior through the Lightweight Charts engine. | This is the closest UX benchmark. FastCharts needs editable drawings, crosshair/readouts, streaming, and state persistence before claiming parity. |
| Highcharts Stock / Highcharts for Python | Mature stock navigator, range controls, data grouping, accessibility/exporting, and a deep technical-indicator surface. | FastCharts can aim for a more Python-native and high-performance open foundation, but Highcharts is far ahead in stock-chart product completeness. |
| Bokeh, Altair, pyecharts/ECharts | Broad interactive or declarative plotting with candlestick examples and useful ecosystem features. | FastCharts can beat these for finance-specific API cohesion and large-data architecture once the finance workflow is hardened. |

Where FastCharts can credibly claim advantage first:

- Large interactive OHLCV and overlay workloads where binary payloads, WebGL2,
  Rust/native kernels, and view-dependent LOD keep browser work bounded.
- Python-native composition: `finance_chart(...)` with independent marks,
  studies, drawings, and tool state instead of an overloaded candlestick API.
- App-level control through Reflex: chart state, drawing state, custom
  tooltips, and user workflows should be controlled from Python application
  state rather than trapped inside a private chart widget.
- TradingView-style overlay breadth for Python users: long/short risk boxes,
  anchored VWAP, fixed/anchored volume profiles, bars pattern, ghost feed,
  sectors, oscillators, and future pattern tools.

Claims to avoid until measured:

- Do not claim "faster than Plotly for finance charts" until OHLC-specific
  payload, first-render, pan/zoom, streaming, and memory benchmarks exist.
- Do not claim "best finance charts in Python" until range selectors, session
  axes, crosshair readouts, editable drawings, persistence, streaming, and
  multi-pane workflows are production-ready.
- Do not compare static libraries and interactive browser libraries as one
  blended category; benchmark static chart-to-pixels and interactive TTFR/latency
  separately.

Required finance benchmark suite:

- OHLC payload build time and bytes for 10k, 100k, and 1M candles.
- First render in headless Chrome for candlestick only, candlestick plus volume,
  candlestick plus overlays, oscillator panes, and volume profiles.
- Pan/zoom latency and frame stability, including OHLC aggregation at different
  viewport widths.
- Streaming append/update latency for new bars and last-bar replacement.
- Browser memory and Python memory for large OHLCV, studies, and drawings.
- Competitor rows for Plotly, mplfinance, Lightweight Charts Python, Highcharts
  Stock where licensing permits, Bokeh, and pyecharts/ECharts.

## Tier 1 Build Order

Build the quant surface 2D-first. The goal is to get the most common trading,
backtesting, and portfolio-analysis views working as composable primitives
before expanding into the long tail of finance tools.

| Priority | Surface | Current status | Next implementation work |
|---|---|---|---|
| 1 | Candlestick / OHLC / line / area price base layer | Candlestick, OHLC, line, and area marks exist; area uses the line decimation path and can fill to the plot bottom or a numeric baseline. | Add candle ordinal/session spacing and richer OHLC tooltip payloads. |
| 2 | Volume subpanel synced beneath price | `volume_bars(source=..., pane="volume")` now materializes OHLCV volume and renders in a synced lower canvas pane beneath price. | Add volume hover/readouts and richer volume scaling/options. |
| 3 | TA overlays and oscillator subpanels | SMA/EMA moving averages, Bollinger bands, cumulative VWAP, and anchored VWAP now compute on the Python side and render as on-price line traces. RSI, MACD, and stochastic now materialize from OHLC sources and render in stacked synced oscillator panes with pane-local y scales. | Add oscillator hover/readouts, configurable pane heights, and native kernels for study computation. |
| 4 | Equity/PnL curve plus drawdown | `performance_chart(...)` and `equity_drawdown(...)` now render the equity/PnL curve in the top pane and drawdown in a synced lower pane, backed by Python reference helpers for equity, returns, drawdown arrays, peak/trough/recovery, and max drawdown. | Add performance hover/readouts, configurable pane sizing, and richer absolute-vs-percent drawdown formatting. |
| 5 | Returns distribution / histogram with VaR/CVaR markers | `returns_distribution_chart(...)` and `returns_distribution(...)` now render a histogram with styleable VaR/CVaR vertical marker lines, backed by Python reference helpers for histogram bins and historical risk metrics. | Add richer hover/readouts, distribution comparison overlays, and more risk marker variants. |

## Core API Decision

Do not add these features as kwargs on `candlestick()`.

`candlestick()` should stay a fast OHLC mark. Forecasts, risk boxes, anchored
VWAP, volume profiles, and patterns should be separate components layered on top
of a composed chart. That keeps the API clean, lets the same tools work with
OHLC bars or future finance marks, and makes it possible to add multiple
overlays without a single overloaded candlestick constructor.

The finance stack should have four object types:

| Type | Examples | Render/data behavior |
|---|---|---|
| `Mark` | candlestick, OHLC, volume bars, line, scatter | Owns data columns and participates in range/tier decisions. |
| `Study` | SMA, EMA, VWAP, Bollinger, anchored VWAP | Computes from one or more source marks and renders as marks. |
| `Drawing` | trendline, sector, position forecast, bars pattern, patterns | User or Python authored anchors plus derived geometry. |
| `ToolState` | active tool, selected drawing, lock/hide/snap, templates | App/editor state, not a data series. |

In the target component API, finance charts should feel like Reflex/Recharts
composition. This sketch is the desired surface, not a claim that each function
exists today:

```python
import fastcharts as fc

fc.finance_chart(
    fc.candlestick(
        x="time",
        open="open",
        high="high",
        low="low",
        close="close",
        volume="volume",
        data=ohlcv,
        id="price",
    ),
    fc.volume_bars(source="price", pane="volume"),
    fc.moving_average(source="price", value="close", window=20, id="sma20"),
    fc.anchored_vwap(source="price", anchor=("2026-01-02", 184.10)),
    fc.long_position(
        source="price",
        entry=("2026-02-03", 191.20),
        stop=184.50,
        target=209.00,
        end="2026-03-01",
        account_size=100_000,
        risk=0.01,
        instrument=fc.instrument(tick_size=0.01, point_value=1.0, lot_size=1.0),
    ),
    fc.xabcd_pattern(
        points=[
            ("2026-01-05", 180.0),
            ("2026-01-19", 205.0),
            ("2026-02-02", 190.0),
            ("2026-02-18", 214.0),
            ("2026-03-04", 196.0),
        ],
        validate="gartley",
    ),
    fc.x_axis(type_="time", session="us_equities"),
    fc.y_axis(side="right", scale="linear"),
    fc.finance_tools(
        active="crosshair",
        snap="ohlc",
        editable=True,
        on_change=handle_drawing_change,
    ),
)
```

The target fluent API can mirror this without becoming the primary design
target:

```python
fig = (
    fc.Figure()
    .candlestick(time, open_, high, low, close, volume=volume, id="price")
    .add(fc.LongPosition(entry=191.20, stop=184.50, target=209.00, source="price"))
    .add(fc.AnchoredVWAP(anchor=anchor, source="price"))
)
```

## Spec Model

The wire spec should remain data-light. Drawings and studies should ship as
small JSON declarations plus binary geometry only when they need computed
arrays.

```json
{
  "tools": {
    "snap": "ohlc",
    "editable": true,
    "selected": "risk-1"
  },
  "layers": [
    {
      "id": "risk-1",
      "role": "drawing",
      "kind": "long_position",
      "source": "price",
      "anchors": {
        "entry": {"x": "2026-02-03", "y": 191.2},
        "stop": {"y": 184.5},
        "target": {"y": 209.0},
        "end": {"x": "2026-03-01"}
      },
      "instrument": {"tick_size": 0.01, "point_value": 1.0, "lot_size": 1.0},
      "risk": {"account_size": 100000, "amount": 0.01, "mode": "fraction"}
    }
  ]
}
```

The client resolves layer geometry against the current axis transform. The
kernel computes only the parts that require data access: anchored VWAP, volume
profiles, indicator values, pattern detection, and any sampled/decimated
forecast geometry.

## Coordinate And Interaction Model

Finance tools need a richer coordinate system than basic x/y traces:

| Coordinate kind | Use cases |
|---|---|
| `data` | Exact timestamp/price anchors. |
| `bar` | Pattern points, bars pattern copies, duration handles. |
| `price` | Horizontal stop/target/entry levels. |
| `pane` | Volume profile histograms and pane-local overlays. |
| `screen` | Labels, handles, drag affordances, hover cards. |

Required interactions:

- GPU or CPU hit testing for non-point geometry, including lines, boxes,
  handles, pattern vertices, and volume profile rows.
- Drag handles with modifier constraints: horizontal, vertical, duplicate, and
  proportional resize.
- Snap modes: none, OHLC, close, high/low, volume profile row, indicator value.
- Drawing lifecycle events: `on_create`, `on_update`, `on_delete`, `on_select`,
  `on_hover`, and `on_commit`.
- Undo/redo command stack for all drawing edits.
- Visibility by timeframe/session, lock/hide, z-order, grouping, and templates.

## Tool Requirements

### Long And Short Position

Long/short position tools are risk calculation drawings, not order execution.
They need:

- Entry, stop, target, and right-edge/end anchors.
- Profit and loss zones rendered as translucent rectangles.
- Instrument metadata: tick size, point value, lot size, quantity precision,
  currency, and leverage.
- Risk metadata: account size, fixed risk amount or account fraction.
- Computed readouts: quantity, risk/reward, target/stop distance in price,
  percent and ticks, PnL, closing account balance, and open/closed state.
- Compact stats mode and axis price labels.

### Position Forecast

Position forecast is a two-point projection with evaluation:

- Source and target anchors.
- Duration until the target time.
- Success/failure classification once price action reaches or expires the
  projected region.
- Styling for source/target labels and result badges.

### Bars Pattern

Bars pattern copies historical price action into a movable drawing:

- Source window over an OHLC mark.
- Destination anchor and optional time/price scaling.
- Display modes: OHLC sticks, candles, or line from open/high/low/close.
- Transform options: mirrored, flipped, normalized to percent move, or raw
  price delta.
- It should reuse candlestick/OHLC render primitives and never duplicate a
  special client renderer unless the shape actually differs.

### Ghost Feed

Ghost feed is a generated future-candle drawing:

- Anchor, direction, number of bars, average high/low in ticks, variance in
  ticks, and optional seed for deterministic output.
- Output is a synthetic OHLC layer with lower opacity and non-authoritative
  labeling.
- It should be explicit that this is a visualization/scenario layer, not a
  statistical forecast.

### Sector

Sector is a projected wedge:

- Origin anchor, future horizon anchor, and target-price anchor.
- Filled polygon with border, labels, and editable handles.
- It should use a generic polygon/fill drawing primitive so it also unlocks
  pattern background fills.

### Anchored VWAP

Anchored VWAP is a study with an anchor:

- Source OHLCV mark and anchor bar/time.
- Price input selection: typical price, close, hlc3, ohlc4.
- Cumulative `sum(price * volume) / sum(volume)` from the anchor.
- Optional standard deviation bands.
- View-dependent recomputation should reuse sorted OHLCV windows and avoid
  re-scanning the full canonical data on every pan.

### Fixed And Anchored Volume Profile

Volume profile is a compute-heavy finance overlay:

- Fixed range: start/end anchors, optional extend right.
- Anchored: start anchor through the latest visible or available bar.
- Row layout: number of rows or ticks per row.
- Volume mode: total, up/down split, delta.
- Value area percentage, point of control, high-volume nodes, low-volume nodes.
- Data policy for high-resolution intrabars: accept precomputed lower-timeframe
  bars from the user first; later add server/kernel downsample requests.
- Render as pane-relative horizontal bars, not ordinary x-axis bars.

### Pattern Drawings

Manual patterns should land before automatic detection:

- ABCD: four editable points, AB=CD, classic ABCD, extension ratios.
- XABCD: five editable points, Gartley, Butterfly, Crab, Bat ratio validation.
- Triangle: three or more points plus optional breakout line.
- Three drives: seven points with ratio labels.
- Head and shoulders: neckline, shoulders/head points, measured move.
- Elliott waves: wave labels, nested degrees, corrective/impulse modes.
- Cycles: cyclic lines, time cycles, sine line.

Pattern validation should return warnings and ratio badges, not block drawing.
Quant users need to see imperfect setups.

## Production Quant Requirements

A finance chart that is credible in a quant/trading setting needs the following
before we should market it as production-grade:

- Time axes with sessions, holidays, range breaks, timezone-aware labels, and
  stable ordinal candle spacing.
- Right-side price axes, optional log scale, percent scale, indexed scale, and
  linked multi-pane crosshair.
- Multi-pane layouts with shared x-axis: price, volume, oscillator, order book,
  and custom study panes.
- Instrument metadata: tick size, tick value, point value, multiplier, lot size,
  currency, trading session, and corporate-action adjustment mode.
- Deterministic calculations for studies and drawings, with parity tests for
  NumPy fallback and native kernels.
- Streaming updates that can append/replace the last bar without rebuilding the
  entire chart or losing drawings.
- Object persistence as stable JSON, including versioning and migration.
- Export fidelity for standalone HTML: drawings and studies must work without a
  live Python kernel when their required geometry has been materialized.
- Reflex integration: every drawing state change can be controlled, observed,
  and customized from Reflex components without forcing React users into a
  private fastcharts UI.

## Implementation Plan

Current status: the Python-side API foundation has started in
`python/fastcharts/finance.py`. It provides `finance_chart`, `finance_tools`,
instrument metadata, serializable finance layers, study/drawing factories, and
long/short position risk metrics. The client-side `LAYER_KINDS` registry has
also started in `js/src/57_layers.js` with canvas rendering for the first
finance overlays. Right-side price axes are wired through `Figure(y_side=...)`
and `fc.y_axis(side="right")`. Area marks have landed as a first-class base
price primitive with fluent and component APIs plus line-style decimation.
`volume_bars` now materializes source OHLCV data and renders as a synced lower
canvas pane beneath the price plot.
Moving averages, Bollinger bands, cumulative VWAP, and anchored VWAP have Python
reference computations and render as composed line studies when their source
data is present. Fixed/anchored volume profile specs can now carry Python-computed
profile rows for total/up-down/delta rendering, `bars_pattern` can materialize
a source OHLC window into projected canvas candles, and `ghost_feed` can create
deterministic synthetic OHLC projections from source candle cadence/range
statistics. The interactive drawing editor, hit-tested handles, snapping edits,
persistence UI, multi-pane layout, native study kernels, and production native
volume-profile kernels are still future work. Performance analytics helpers for
equity curves, returns, drawdown, returns distributions, and historical VaR/CVaR
have also landed as Python reference functions. The Tier 1 performance chart now
uses those helpers to render equity/PnL plus a synced lower drawdown pane, and
the returns-distribution chart now renders histogram bars with VaR/CVaR marker
lines.

### Phase 1: Overlay Layer Foundation

- Add `Layer`/`Drawing`/`Study` dataclasses and a stable JSON schema.
  Python-side serializable layer objects have started; explicit `Drawing` and
  `Study` subclasses can be split from the generic `Layer` when the renderer
  needs type-specific behavior.
- Add component factories for `finance_chart`, `finance_tools`, and basic
  drawing components. Initial factories now cover position tools, forecast
  drawings, bars pattern, ghost feed, sector, volume studies, and ABCD/XABCD
  pattern specs.
- Add client layer registry parallel to `MARK_KINDS`: `LAYER_KINDS[kind]`.
  Initial canvas renderers now cover position boxes, projection lines, sectors,
  anchored-study markers, fixed ranges, computed volume profiles, materialized
  bars patterns, ghost feed, and ABCD/XABCD patterns.
- Add screen/data coordinate conversion helpers and draggable anchor handles.
- Add selection, hover, z-order, lock/hide, and delete behavior for drawings.
- Add tests for JSON round-trip, coordinate transforms, and event payloads.

### Phase 2: Finance Axes And Panes

- Add right-side y-axis support and pane layout. Right-side y-axis support has
  landed for single-pane charts; pane layout remains.
- Add volume bars in a separate pane linked to the candlestick source.
- Add range breaks/session-aware time axes and stable candle ordinal spacing.
- Add linked crosshair across panes with OHLC readout and Reflex-customizable
  tooltip payloads.

### Phase 3: Risk And Measurement Tools

- Implement price range, date range, and date+price range.
- Implement long and short position with full quantity/risk/PnL formulas.
- Implement position forecast and sector.
- Add compact stats mode and price-axis labels.

### Phase 4: Forecasting Drawings

- Implement bars pattern by copying source OHLC windows into a movable synthetic
  OHLC layer. Initial materialization/rendering has landed for static projected
  candles; interactive movement and edit handles remain.
- Implement ghost feed as deterministic synthetic candles with styling that
  clearly separates it from real market data. Initial data-space materialization
  and canvas rendering have landed; drag/edit controls remain.
- Add templates for common forecast/risk presets.

### Phase 5: Volume Studies

- Implement anchored VWAP and optional bands. Python-side AVWAP computation and
  composed line/band traces have started; native acceleration and streaming
  updates remain.
- Implement fixed range and anchored volume profile with total/up-down/delta
  modes, value area, and point-of-control labels. Python-side profile rows and
  canvas rendering have started; native acceleration and richer labels remain.
- Add native and NumPy parity tests for AVWAP and volume-profile kernels.

### Phase 6: Pattern Drawings

- Implement ABCD and XABCD manual drawings with ratio labels and validation.
- Add triangle, three drives, head and shoulders, Elliott waves, and cycle tools.
- Add snap-to-OHLC for pattern points and visibility-by-timeframe.

### Phase 7: Auto Detection And Quant Extensions

- Add optional pattern detectors as studies that emit candidate pattern layers.
- Add market profile, depth chart, order book heatmap, Renko, Heikin-Ashi, Kagi,
  point-and-figure, and indicator library breadth.
- Add benchmarks for pan/zoom latency with hundreds of drawings and millions of
  OHLCV rows.

## Definition Of Done

This roadmap is complete when:

- A user can build a candlestick chart with volume, studies, long/short risk
  boxes, forecasts, volume profiles, and chart patterns entirely through the
  component API.
- The same state can be edited interactively, persisted to JSON, restored, and
  controlled from Reflex.
- Pan/zoom remains interactive on multi-million-row OHLCV datasets because
  studies and overlays are either screen-bounded, incrementally computed, or
  precomputed.
- Native and NumPy fallback calculations match for all finance kernels.
- The example Reflex app contains a finance-workstation page exercising the
  major tools side by side.
