# XY TERMINAL

XY TERMINAL is a dense, professional-market workstation built entirely in
[Reflex](https://reflex.dev) with the `xy[reflex]` integration. It demonstrates
finance charts, state-driven figures, fixed and streamed data, and semantic
chart events in one responsive page.

> **SIMULATED DATA** — every quote, price series, position, news story,
> economic event, and risk result in this example is fictional and generated
> locally from fixed seeds. The app does not contact a market-data service,
> submit orders, or require an API key. It is an interface and charting demo,
> not investment advice.

The black-and-amber visual language is inspired by professional market
terminals, but the app does not use third-party brand names, logos, assets, or data.

## Workspaces

- **Markets (`MKTS`)** — a landing-page SPY `FinanceChart` with native OHLCV,
  studies, oscillator, projection, and finance tools, plus cross-asset quotes,
  movers, breadth, a market heatmap, the yield curve, and a live pulse fed
  through `reflex_xy.append()`.
- **Security (`DES <symbol>`)** — daily or weekly OHLCV, range controls,
  overlays, oscillator panes, finance drawing presets, key statistics,
  related stories, and a paper-only position-risk ticket.
- **Portfolio (`PORT`)** — deterministic positions, NAV and P&L, equity and
  drawdown, allocation, contribution, and exposure. Choosing a position opens
  its Security workspace.
- **Risk (`RISK`)** — return distribution with VaR/CVaR, correlations, factor
  exposure, confidence controls, and deterministic stress scenarios.
- **News (`NEWS`)** — simulated stories with sentiment and impact metadata,
  story detail, and a fictional economic calendar.

The persistent shell also includes a ticker tape, watchlist, context rail,
function-key navigation, status line, and a developer drawer. The drawer shows
live Python source, a compact Reflex-state snapshot, and an abbreviated XY
chart/layer specification.

## Commands

Type a command in the top command bar and press Enter:

| Command | Result |
| --- | --- |
| `MKTS` | Open Markets |
| `DES AAPL` | Open the Security workspace for a known symbol |
| `PORT` | Open Portfolio |
| `RISK` | Open Risk |
| `NEWS` | Open News |
| `HELP` | Show the command reference |

Commands and symbols are case-insensitive. Unknown input stays in the app and
produces an inline status message.

## Run

From this directory:

```bash
cd examples/reflex
uv run reflex run
```

`uv run` resolves this directory's [`pyproject.toml`](pyproject.toml), including
the editable local `xy[reflex]` package. Open the URL printed by Reflex
(normally <http://localhost:3000>). No environment variables or external
services are required.

## Architecture

The `xy_reflex_demo` package is split by responsibility:

- `data.py` defines typed instrument, quote, position, story, calendar, and
  scenario models. Cached NumPy generators create three years of seeded daily
  OHLCV as of the fixed date displayed in the app.
- `charts.py` contains pure data transforms and chart builders for all five
  workspaces, including finance studies and drawings.
- `state.py` keeps only small UI selections and inputs in Reflex state. It
  owns command routing, semantic chart events, paper-ticket validation, and
  one guarded background quote loop.
- `components.py` composes the persistent terminal shell and responsive
  workspace views; the package entry point registers the single page.

State-dependent Security, Portfolio, and Risk charts use
`@reflex_xy.figure`. The first Markets panel is a direct, fixed-data
`xy.FinanceChart`, so the new finance surface is visible immediately rather
than only after a Security drilldown. Other fixed views exercise a direct
`xy.Chart` and the kernel-backed `reflex_xy.inline()` tier. The live pulse
starts with a figure token and receives compact points through
`reflex_xy.append()`. Hover and view-change events are handled as ordinary
Reflex events; there is no iframe or `postMessage` bridge.

The adapter is enabled by `reflex_xy.XYPlugin()` in
[`rxconfig.py`](rxconfig.py). Chart payloads travel through the app's XY
websocket namespace while Reflex state retains only lightweight selections
and token strings.

## Paper ticket

The Security ticket accepts side, entry, stop, target, account size, and risk
percentage. A valid setup updates the long/short chart overlay and displays
risk, quantity, and reward/risk metrics. Invalid ordering is explained inline
and suppresses the overlay. The button does not place or simulate an order.

## Checks

From the repository root, the focused test covers deterministic data, OHLC
invariants, portfolio/risk calculations, representative chart specs, linking
tiers, semantic events, and app composition:

```bash
uv run pytest tests/test_example_apps.py -q
```
