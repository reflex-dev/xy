"""Terminal shell and workspace components for the Reflex example."""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping, Sequence
from typing import Any

import reflex as rx

import reflex_xy
from reflex_xy.tokens import BUILDER_ATTR

from . import charts, data
from .state import (
    CONFIDENCE_LEVELS,
    DRAWINGS,
    OSCILLATORS,
    OVERLAYS,
    RANGES,
    RESOLUTIONS,
    TerminalState,
)

INK = "#050505"
PANEL = "#0b0c0c"
PANEL_ALT = "#111313"
BORDER = "#34301f"
AMBER = "#ffb000"
AMBER_SOFT = "#d08d00"
GREEN = "#27d17f"
RED = "#ff5a5f"
CYAN = "#57c7ff"
TEXT = "#ece7d7"
MUTED = "#8e8a7b"
MONO = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"

AS_OF = str(getattr(data, "AS_OF_DATE", getattr(data, "AS_OF", "2026-07-31")))

# The yield curve intentionally uses the kernel-served fixed-data tier while
# the market heatmap below is passed as a direct xy.Chart static payload.
YIELD_CURVE_TOKEN = reflex_xy.inline(charts.YIELD_CURVE_CHART)


def _get(obj: Any, *names: str, default: Any = "—") -> Any:
    for name in names:
        if isinstance(obj, Mapping) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _items(value: Any) -> list[tuple[str, Any]]:
    if isinstance(value, Mapping):
        return [(str(key), item) for key, item in value.items()]
    return []


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _money(value: Any, *, decimals: int = 2) -> str:
    number = _float(value)
    sign = "-" if number < 0 else ""
    return f"{sign}${abs(number):,.{decimals}f}"


def _percent(value: Any) -> str:
    number = _float(value)
    return f"{number:+.2f}%"


def _signed_color(value: Any) -> str:
    return GREEN if _float(value) >= 0 else RED


def _compact_timestamp(value: Any, *, include_date: bool = False) -> str:
    """Format the deterministic ISO timestamps for dense terminal rows."""
    text = str(value)
    if len(text) >= 16 and text[10:11] == "T":
        return f"{text[5:10]} {text[11:16]}" if include_date else text[11:16]
    return text


def terminal_button(
    label: Any,
    *,
    on_click: Any = None,
    active: Any = False,
    compact: bool = False,
    **props: Any,
) -> rx.Component:
    return rx.button(
        label,
        on_click=on_click,
        variant="surface",
        radius="none",
        box_shadow="none",
        margin="0",
        flex_shrink="0",
        white_space="nowrap",
        min_height="25px" if compact else "30px",
        padding="2px 7px" if compact else "4px 9px",
        border=f"1px solid {AMBER}" if active is True else f"1px solid {BORDER}",
        background=AMBER if active is True else PANEL_ALT,
        color=INK if active is True else AMBER,
        font_family=MONO,
        font_size="10px" if compact else "11px",
        font_weight="700",
        letter_spacing="0.04em",
        cursor="pointer",
        _hover={"background": AMBER, "color": INK, "border_color": AMBER},
        _focus_visible={"outline": f"2px solid {CYAN}", "outline_offset": "2px"},
        **props,
    )


def state_button(label: str, value: Any, event: Any, *, compact: bool = True) -> rx.Component:
    """A terminal button whose selected state is a Reflex boolean var."""
    return rx.button(
        label,
        on_click=event,
        variant="surface",
        radius="none",
        box_shadow="none",
        margin="0",
        flex_shrink="0",
        white_space="nowrap",
        min_height="25px" if compact else "30px",
        padding="2px 7px" if compact else "4px 9px",
        border=f"1px solid {BORDER}",
        background=rx.cond(value, AMBER, PANEL_ALT),
        color=rx.cond(value, INK, AMBER),
        font_family=MONO,
        font_size="10px" if compact else "11px",
        font_weight="700",
        cursor="pointer",
        _hover={"border_color": AMBER},
        _focus_visible={"outline": f"2px solid {CYAN}", "outline_offset": "2px"},
    )


def panel(
    title: Any,
    *children: rx.Component,
    subtitle: Any | None = None,
    action: rx.Component | None = None,
    **props: Any,
) -> rx.Component:
    header_children: list[rx.Component] = [
        rx.text(
            title,
            color=AMBER,
            font_family=MONO,
            font_size="11px",
            font_weight="800",
            letter_spacing="0.08em",
            text_transform="uppercase",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        )
    ]
    if subtitle is not None:
        header_children.append(
            rx.text(
                subtitle,
                color=MUTED,
                font_family=MONO,
                font_size="9px",
                margin_left="8px",
                min_width="0",
                overflow="hidden",
                text_overflow="ellipsis",
                white_space="nowrap",
            )
        )
    props.setdefault("width", "100%")
    return rx.box(
        rx.hstack(
            rx.hstack(*header_children, spacing="1", align="center", min_width="0"),
            rx.box(action or rx.box(), flex_shrink="0"),
            justify="between",
            align="center",
            min_height="28px",
            padding="4px 7px",
            border_bottom=f"1px solid {BORDER}",
            background="#16140c",
        ),
        rx.box(*children, padding="7px", width="100%"),
        background=PANEL,
        border=f"1px solid {BORDER}",
        min_width="0",
        overflow="hidden",
        **props,
    )


def metric(label: str, value: Any, *, color: str = TEXT, note: Any = None) -> rx.Component:
    return rx.box(
        rx.text(label, color=MUTED, font_family=MONO, font_size="9px", letter_spacing="0.06em"),
        rx.text(
            value,
            color=color,
            font_family=MONO,
            font_size="16px",
            font_weight="750",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        rx.text(note, color=MUTED, font_family=MONO, font_size="9px")
        if note is not None
        else rx.box(),
        min_width="0",
    )


def terminal_select(options: Sequence[str], value: Any, on_change: Any, label: str) -> rx.Component:
    return rx.vstack(
        rx.text(label, color=MUTED, font_size="9px", font_family=MONO),
        rx.select(
            list(options),
            value=value,
            on_change=on_change,
            size="1",
            radius="none",
            width="100%",
            color_scheme="amber",
        ),
        spacing="1",
        align="start",
        min_width="110px",
    )


def terminal_input(label: str, value: Any, on_change: Any, **props: Any) -> rx.Component:
    return rx.vstack(
        rx.text(label, color=MUTED, font_family=MONO, font_size="9px"),
        rx.input(
            value=value,
            on_change=on_change,
            size="1",
            radius="none",
            background=INK,
            border=f"1px solid {BORDER}",
            color=TEXT,
            font_family=MONO,
            font_size="11px",
            _focus={"border_color": CYAN, "box_shadow": f"0 0 0 1px {CYAN}"},
            **props,
        ),
        spacing="1",
        align="start",
        min_width="0",
    )


def command_bar() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text("XY", color=INK, background=AMBER, padding="3px 7px", font_weight="900"),
            rx.text(
                "COMMAND",
                color=AMBER,
                font_weight="800",
                font_size="10px",
                display=rx.breakpoints(initial="none", md="block"),
            ),
            rx.input(
                value=TerminalState.command,
                on_change=TerminalState.set_command,
                on_key_down=TerminalState.command_key,
                placeholder="MKTS  |  DES AAPL  |  PORT  |  RISK  |  NEWS  |  HELP",
                aria_label="Terminal command",
                radius="none",
                size="2",
                background=INK,
                border=f"1px solid {AMBER_SOFT}",
                color=TEXT,
                font_family=MONO,
                font_size="12px",
                flex="1",
                min_width="0",
                _placeholder={"color": MUTED},
                _focus={"border_color": CYAN, "box_shadow": f"0 0 0 1px {CYAN}"},
            ),
            terminal_button("GO", on_click=TerminalState.execute_command, compact=False),
            rx.text(
                "SIM DATA",
                color=INK,
                background=RED,
                font_family=MONO,
                font_size="9px",
                font_weight="900",
                padding="4px 7px",
                white_space="nowrap",
                display=rx.breakpoints(initial="block", sm="none"),
                flex_shrink="0",
            ),
            rx.text(
                "SIMULATED DATA",
                color=INK,
                background=RED,
                font_family=MONO,
                font_size="9px",
                font_weight="900",
                padding="4px 7px",
                white_space="nowrap",
                display=rx.breakpoints(initial="none", sm="block"),
                flex_shrink="0",
            ),
            width="100%",
            align="center",
            gap=rx.breakpoints(initial="4px", sm="8px"),
        ),
        rx.cond(
            TerminalState.help_visible,
            rx.text(
                "MKTS  Global markets    DES <SYMBOL>  Security    PORT  Portfolio    "
                "RISK  Risk monitor    NEWS  Newswire",
                color=CYAN,
                font_family=MONO,
                font_size="10px",
                padding="4px 8px",
                border=f"1px solid {CYAN}",
                width="100%",
            ),
            rx.box(),
        ),
        spacing="1",
        width="100%",
    )


def ticker_tape() -> rx.Component:
    return rx.hstack(
        rx.foreach(TerminalState.tape_quotes, _live_quote_cell),
        width="100%",
        overflow_x="auto",
        spacing="0",
        background="#080909",
        border_top=f"1px solid {BORDER}",
        border_bottom=f"1px solid {BORDER}",
        font_family=MONO,
        font_size="10px",
        scrollbar_width="thin",
    )


def _live_quote_cell(row: rx.Var[dict[str, str]]) -> rx.Component:
    return rx.hstack(
        rx.text(row["symbol"], color=AMBER, font_weight="800"),
        rx.text(row["last"], color=TEXT),
        rx.text(
            row["change"],
            color=rx.cond(row["direction"] == "UP", GREEN, RED),
        ),
        spacing="2",
        align="center",
        padding="2px 9px",
        border_right=f"1px solid {BORDER}",
        white_space="nowrap",
    )


def watchlist() -> rx.Component:
    rows = list(data.watchlist_rows())
    entries = []
    for row in rows:
        symbol = str(_get(row, "symbol", "ticker"))
        last = _get(row, "last", "price", "close", default=0.0)
        change = _get(
            row,
            "change_percent",
            "change_pct",
            "percent_change",
            "pct_change",
            default=0.0,
        )
        entries.append(
            rx.button(
                rx.grid(
                    rx.text(symbol, color=AMBER, font_weight="800"),
                    rx.text(f"{_float(last):,.2f}", color=TEXT, text_align="right"),
                    rx.text(_percent(change), color=_signed_color(change), text_align="right"),
                    grid_template_columns="minmax(64px, 1fr) minmax(70px, 1fr) 68px",
                    width="100%",
                    align_items="center",
                ),
                on_click=TerminalState.select_symbol(symbol),
                variant="surface",
                radius="none",
                box_shadow="none",
                background="transparent",
                width="100%",
                min_height="27px",
                padding="3px 5px",
                border_bottom="1px solid #1d1d19",
                font_family=MONO,
                font_size="10px",
                _hover={"background": "#231c08"},
                _focus_visible={"outline": f"2px solid {CYAN}", "outline_offset": "-2px"},
            )
        )
    return panel(
        "Watchlist",
        rx.vstack(*entries, spacing="0", width="100%"),
        subtitle=f"{len(entries)} securities",
        padding="0",
        height="100%",
    )


def _breadth_cards() -> rx.Component:
    breadth = data.breadth_metrics()
    cards = []
    for label, value in _items(breadth):
        display = _percent(value) if "percent" in label else value
        cards.append(metric(label.replace("_", " "), display))
    return rx.grid(*cards, columns=rx.breakpoints(initial="2", md="4"), gap="10px", width="100%")


def _movers_table() -> rx.Component:
    rows = list(data.movers())
    body = []
    for row in rows:
        symbol = str(_get(row, "symbol", "ticker"))
        change = _get(
            row,
            "change_percent",
            "change_pct",
            "percent_change",
            "pct_change",
            default=0.0,
        )
        body.append(
            rx.grid(
                rx.text(symbol, color=AMBER, font_weight="800"),
                rx.text(
                    str(_get(row, "name", "label", default=symbol)),
                    color=TEXT,
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
                rx.text(_percent(change), color=_signed_color(change), text_align="right"),
                grid_template_columns="64px minmax(0, 1fr) 62px",
                width="100%",
                padding="4px 2px",
                border_bottom="1px solid #1d1d19",
                font_family=MONO,
                font_size="10px",
            )
        )
    return rx.vstack(*body, spacing="0", width="100%")


def markets_workspace() -> rx.Component:
    return rx.vstack(
        panel(
            "Market focus · SPY",
            rx.box(
                reflex_xy.chart(
                    charts.MARKET_FOCUS_CHART,
                    height=rx.breakpoints(initial="390px", sm="520px"),
                    min_width=rx.breakpoints(initial="520px", sm="100%"),
                    id="market-finance-chart",
                ),
                width="100%",
                overflow_x="auto",
                scrollbar_width="thin",
            ),
            subtitle="native FinanceChart · OHLCV · studies · tools",
            action=terminal_button(
                "DES SPY",
                on_click=TerminalState.select_symbol("SPY"),
                compact=True,
            ),
        ),
        rx.grid(
            panel(
                "Market breadth",
                _breadth_cards(),
                grid_column=rx.breakpoints(initial="1", md="span 2"),
            ),
            panel("Top movers", _movers_table()),
            columns=rx.breakpoints(initial="1", md="3"),
            gap="8px",
            width="100%",
        ),
        rx.grid(
            panel(
                "Cross-asset heatmap",
                reflex_xy.chart(charts.MARKET_HEATMAP_CHART, height="300px", id="market-heatmap"),
                subtitle="direct xy.Chart payload",
            ),
            panel(
                "Yield curve",
                reflex_xy.chart(YIELD_CURVE_TOKEN, height="300px", id="yield-curve"),
                subtitle="inline() kernel token",
            ),
            columns=rx.breakpoints(initial="1", md="2"),
            gap="8px",
            width="100%",
        ),
        panel(
            "Live market pulse",
            reflex_xy.chart(TerminalState.market_pulse, height="230px", id="market-pulse"),
            subtitle="append-driven stream",
            action=terminal_button(
                rx.cond(TerminalState.streaming, "STOP", "GO LIVE"),
                on_click=TerminalState.stream_quotes,
            ),
        ),
        spacing="2",
        width="100%",
    )


def _selected_instrument_card() -> rx.Component:
    fallback: rx.Component = rx.box()
    for symbol in reversed(data.instrument_symbols()):
        instrument = data.instrument(symbol)
        quote = data.quote(symbol)
        content = rx.vstack(
            rx.text(
                str(_get(instrument, "name", "description", default=symbol)), color=TEXT, size="2"
            ),
            rx.grid(
                metric("LAST", _money(quote.last), color=TEXT),
                metric(
                    "DAY CHANGE",
                    _percent(quote.change_percent),
                    color=_signed_color(quote.change_percent),
                ),
                metric("VOLUME", f"{quote.volume:,.0f}"),
                metric(
                    "ASSET",
                    str(_get(instrument, "asset_class", "kind", default="Security")),
                ),
                metric("SECTOR", str(_get(instrument, "sector", default="Global"))),
                metric("BETA", f"{_float(_get(instrument, 'beta', default=0)):.2f}"),
                metric("VENUE", str(_get(instrument, "exchange", "venue", default="Global"))),
                metric("CCY", str(_get(instrument, "currency", default="USD"))),
                columns=rx.breakpoints(initial="1", sm="2", md="4"),
                gap="8px",
                width="100%",
            ),
            spacing="2",
            width="100%",
        )
        fallback = rx.cond(TerminalState.selected_symbol == str(symbol), content, fallback)
    return fallback


def security_controls() -> rx.Component:
    return panel(
        "Security controls",
        rx.vstack(
            rx.flex(
                terminal_select(
                    list(data.instrument_symbols()),
                    TerminalState.selected_symbol,
                    TerminalState.select_symbol,
                    "SYMBOL",
                ),
                rx.vstack(
                    rx.text("RANGE", color=MUTED, font_size="9px", font_family=MONO),
                    rx.hstack(
                        *[
                            state_button(
                                value,
                                TerminalState.range_key == value,
                                TerminalState.set_range_key(value),
                            )
                            for value in RANGES
                        ],
                        spacing="1",
                        wrap="wrap",
                    ),
                    spacing="1",
                    align="start",
                ),
                rx.vstack(
                    rx.text("RESOLUTION", color=MUTED, font_size="9px", font_family=MONO),
                    rx.hstack(
                        *[
                            state_button(
                                value,
                                TerminalState.resolution == value,
                                TerminalState.set_resolution(value),
                            )
                            for value in RESOLUTIONS
                        ],
                        spacing="1",
                    ),
                    spacing="1",
                    align="start",
                ),
                gap="10px",
                width="100%",
                wrap="wrap",
                align="end",
            ),
            rx.vstack(
                rx.text("OVERLAYS", color=MUTED, font_size="9px", font_family=MONO),
                rx.hstack(
                    *[
                        state_button(
                            overlay,
                            TerminalState.overlays.contains(overlay),
                            TerminalState.toggle_overlay(overlay),
                        )
                        for overlay in OVERLAYS
                    ],
                    spacing="1",
                    wrap="wrap",
                ),
                spacing="1",
                align="start",
            ),
            rx.flex(
                terminal_select(
                    OSCILLATORS,
                    TerminalState.oscillator,
                    TerminalState.set_oscillator,
                    "OSCILLATOR",
                ),
                terminal_select(
                    DRAWINGS, TerminalState.drawing, TerminalState.set_drawing, "DRAWING PRESET"
                ),
                gap="10px",
                width="100%",
                wrap="wrap",
            ),
            spacing="2",
            width="100%",
        ),
    )


def paper_ticket() -> rx.Component:
    return panel(
        "Paper risk ticket",
        rx.vstack(
            rx.grid(
                terminal_select(
                    ("Long", "Short"),
                    TerminalState.ticket_side,
                    TerminalState.set_ticket_side,
                    "SIDE",
                ),
                terminal_input("ENTRY", TerminalState.ticket_entry, TerminalState.set_ticket_entry),
                terminal_input("STOP", TerminalState.ticket_stop, TerminalState.set_ticket_stop),
                terminal_input(
                    "TARGET", TerminalState.ticket_target, TerminalState.set_ticket_target
                ),
                columns=rx.breakpoints(initial="1", sm="2", md="4"),
                gap="7px",
                width="100%",
            ),
            rx.grid(
                terminal_input(
                    "ACCOUNT SIZE", TerminalState.ticket_account, TerminalState.set_ticket_account
                ),
                terminal_input("RISK %", TerminalState.ticket_risk, TerminalState.set_ticket_risk),
                metric("RISK AMOUNT", TerminalState.ticket_risk_amount),
                metric("POSITION SIZE", TerminalState.ticket_position_size),
                metric("REWARD / RISK", TerminalState.ticket_reward_risk),
                columns=rx.breakpoints(initial="1", sm="2", md="5"),
                gap="8px",
                width="100%",
            ),
            rx.cond(
                TerminalState.ticket_valid,
                rx.text(
                    "VALID PAPER SCENARIO — NO ORDER WILL BE SUBMITTED",
                    color=GREEN,
                    font_family=MONO,
                    font_size="9px",
                ),
                rx.text(TerminalState.ticket_error, color=RED, font_family=MONO, font_size="9px"),
            ),
            spacing="2",
            width="100%",
        ),
        subtitle="simulation only",
    )


def _story_teasers(stories: Sequence[Any]) -> rx.Component:
    return rx.vstack(
        *[
            rx.box(
                rx.text(
                    str(_get(story, "timestamp", "time", default="--:--")),
                    color=CYAN,
                    font_size="9px",
                ),
                rx.text(str(_get(story, "headline", "title")), color=TEXT, font_size="10px"),
                padding="5px 0",
                border_bottom="1px solid #1d1d19",
                width="100%",
            )
            for story in stories[:4]
        ],
        spacing="0",
        width="100%",
        font_family=MONO,
    )


def _related_news() -> rx.Component:
    result: rx.Component = rx.text("NO RELATED STORIES", color=MUTED, font_size="9px")
    for symbol in reversed(data.instrument_symbols()):
        stories = data.stories(symbol)
        content = _story_teasers(stories) if stories else result
        result = rx.cond(TerminalState.selected_symbol == symbol, content, result)
    return result


def security_workspace() -> rx.Component:
    return rx.vstack(
        security_controls(),
        panel(
            rx.hstack(
                rx.text(TerminalState.selected_symbol, color=AMBER, font_weight="900"),
                rx.text("OHLCV ANALYSIS", color=TEXT),
                spacing="2",
            ),
            rx.box(
                reflex_xy.chart(
                    TerminalState.security_figure,
                    on_hover=TerminalState.on_chart_hover,
                    on_view_change=TerminalState.on_chart_view,
                    height=rx.breakpoints(initial="430px", sm="610px"),
                    min_width=rx.breakpoints(initial="480px", sm="100%"),
                    id="security-chart",
                ),
                width="100%",
                overflow_x="auto",
                scrollbar_width="thin",
            ),
            subtitle=TerminalState.view_status,
        ),
        rx.grid(
            panel("Instrument", _selected_instrument_card()),
            panel("Related news", _related_news()),
            columns=rx.breakpoints(initial="1", md="2"),
            gap="8px",
            width="100%",
        ),
        paper_ticket(),
        spacing="2",
        width="100%",
    )


def _summary_metrics() -> rx.Component:
    summary = data.portfolio_summary()
    items = _items(summary)
    return rx.grid(
        *[
            metric(
                label.replace("_", " "),
                (
                    f"{_float(value):.2f}%"
                    if "percent" in label.lower()
                    else _money(value)
                    if any(key in label.lower() for key in ("nav", "pnl", "value", "cash", "cost"))
                    else value
                ),
                color=_signed_color(value) if "pnl" in label.lower() else TEXT,
            )
            for label, value in items
        ],
        columns=rx.breakpoints(initial="2", md="4"),
        gap="12px",
        width="100%",
    )


def positions_table() -> rx.Component:
    column_template = "70px 80px 120px 110px 85px"
    rows = []
    for position in data.position_rows():
        symbol = str(_get(position, "symbol", "ticker"))
        pnl = _get(position, "pnl", "unrealized_pnl", "profit_loss", default=0.0)
        rows.append(
            rx.button(
                rx.grid(
                    rx.text(symbol, color=AMBER, font_weight="900"),
                    rx.text(
                        f"{_float(_get(position, 'quantity', 'units', default=0)):,.2f}",
                        text_align="right",
                    ),
                    rx.text(
                        _money(_get(position, "market_value", "value", default=0)),
                        text_align="right",
                    ),
                    rx.text(_money(pnl), color=_signed_color(pnl), text_align="right"),
                    rx.text(
                        _percent(
                            _get(
                                position,
                                "pnl_percent",
                                "pnl_pct",
                                "return_pct",
                                default=0,
                            )
                        ),
                        color=_signed_color(pnl),
                        text_align="right",
                    ),
                    grid_template_columns=column_template,
                    width="100%",
                ),
                on_click=TerminalState.drilldown_position(symbol),
                variant="surface",
                radius="none",
                box_shadow="none",
                background="transparent",
                min_height="30px",
                padding="4px 3px",
                width="100%",
                color=TEXT,
                font_family=MONO,
                font_size="10px",
                border_bottom="1px solid #1d1d19",
                _hover={"background": "#231c08"},
            )
        )
    return rx.box(
        rx.vstack(
            rx.grid(
                *[
                    rx.text(label, color=MUTED, text_align="right" if index else "left")
                    for index, label in enumerate(("SYMBOL", "QTY", "MKT VALUE", "P&L", "RETURN"))
                ],
                grid_template_columns=column_template,
                width="100%",
                padding="3px",
                font_family=MONO,
                font_size="9px",
            ),
            *rows,
            spacing="0",
            min_width="465px",
            width="100%",
        ),
        width="100%",
        overflow_x="auto",
    )


def portfolio_workspace() -> rx.Component:
    return rx.vstack(
        panel("Portfolio summary", _summary_metrics(), subtitle="fictional multi-asset book"),
        panel(
            "NAV & drawdown",
            reflex_xy.chart(
                TerminalState.portfolio_figure, height="330px", id="portfolio-performance"
            ),
            subtitle="@reflex_xy.figure",
        ),
        panel("Positions", positions_table(), subtitle="select a row for DES"),
        rx.grid(
            panel(
                "Allocation",
                reflex_xy.chart(
                    charts.portfolio_allocation_chart(), height="245px", id="portfolio-allocation"
                ),
            ),
            panel(
                "Contribution",
                reflex_xy.chart(
                    charts.portfolio_contribution_chart(),
                    height="245px",
                    id="portfolio-contribution",
                ),
            ),
            panel(
                "Exposure",
                reflex_xy.chart(
                    charts.portfolio_exposure_chart(), height="245px", id="portfolio-exposure"
                ),
            ),
            columns=rx.breakpoints(initial="1", md="2", lg="3"),
            gap="8px",
            width="100%",
        ),
        spacing="2",
        width="100%",
    )


def scenario_table(confidence: float = 0.95) -> rx.Component:
    column_template = "140px minmax(230px, 1fr) 110px"
    scenarios = list(data.stress_scenarios(confidence))
    rows = []
    for scenario in scenarios:
        name = str(_get(scenario, "name", "scenario", "label"))
        impact = _get(scenario, "impact", "pnl", "portfolio_impact", default=0.0)
        rows.append(
            rx.button(
                rx.grid(
                    rx.text(name, color=AMBER, font_weight="800"),
                    rx.text(
                        str(_get(scenario, "shock", "description", default="Deterministic shock")),
                        color=MUTED,
                    ),
                    rx.text(
                        _money(impact),
                        color=_signed_color(impact),
                        text_align="right",
                        white_space="nowrap",
                    ),
                    grid_template_columns=column_template,
                    width="100%",
                ),
                on_click=TerminalState.set_scenario(name),
                variant="surface",
                radius="none",
                box_shadow="none",
                width="100%",
                min_height="30px",
                color=TEXT,
                font_family=MONO,
                font_size="10px",
                border_bottom="1px solid #1d1d19",
                background=rx.cond(
                    TerminalState.selected_scenario == name, "#231c08", "transparent"
                ),
                _hover={"background": "#231c08"},
            )
        )
    return rx.box(
        rx.vstack(*rows, spacing="0", width="100%", min_width="520px"),
        width="100%",
        overflow_x="auto",
    )


def risk_workspace() -> rx.Component:
    return rx.vstack(
        panel(
            "Risk controls",
            rx.hstack(
                rx.text("CONFIDENCE", color=MUTED, font_family=MONO, font_size="9px"),
                *[
                    state_button(
                        confidence,
                        TerminalState.confidence_label == confidence,
                        TerminalState.set_confidence(confidence),
                    )
                    for confidence in CONFIDENCE_LEVELS
                ],
                spacing="1",
                align="center",
                wrap="wrap",
            ),
        ),
        rx.grid(
            panel(
                "Historical VaR / CVaR",
                reflex_xy.chart(TerminalState.risk_figure, height="310px", id="risk-distribution"),
                subtitle=TerminalState.confidence_label,
            ),
            panel(
                "Correlation matrix",
                reflex_xy.chart(
                    charts.risk_correlation_chart(), height="310px", id="risk-correlation"
                ),
            ),
            columns=rx.breakpoints(initial="1", md="2"),
            gap="8px",
            width="100%",
        ),
        rx.grid(
            panel(
                "Factor exposure",
                reflex_xy.chart(charts.risk_factor_chart(), height="265px", id="risk-factors"),
            ),
            panel(
                "Stress scenarios",
                rx.cond(
                    TerminalState.confidence_label == "99%",
                    scenario_table(0.99),
                    scenario_table(0.95),
                ),
                subtitle="select scenario",
            ),
            columns=rx.breakpoints(initial="1", md="2"),
            gap="8px",
            width="100%",
        ),
        spacing="2",
        width="100%",
    )


def _story_id(story: Any) -> str:
    return str(_get(story, "id", "story_id", default="N001"))


def _story_detail(story: Any) -> rx.Component:
    sentiment = _get(story, "sentiment", default="Neutral")
    impact = _get(story, "impact", "importance", default="Medium")
    return rx.vstack(
        rx.hstack(
            rx.text(str(_get(story, "source", default="XY NEWS")), color=CYAN),
            rx.text(
                _compact_timestamp(
                    _get(story, "timestamp", "time", default="--:--"), include_date=True
                ),
                color=MUTED,
            ),
            spacing="2",
        ),
        rx.heading(str(_get(story, "headline", "title")), color=TEXT, size="4", font_family=MONO),
        rx.hstack(
            rx.text(
                f"SENTIMENT {sentiment}",
                color=GREEN
                if str(sentiment).lower() == "positive"
                else RED
                if str(sentiment).lower() == "negative"
                else AMBER,
            ),
            rx.text(f"IMPACT {impact}", color=AMBER),
            spacing="3",
            font_size="10px",
        ),
        rx.text(
            str(_get(story, "body", "summary", "description", default="Simulated market story.")),
            color=TEXT,
            font_family=MONO,
            font_size="12px",
            line_height="1.6",
        ),
        spacing="3",
        align="start",
        width="100%",
    )


def news_list() -> rx.Component:
    rows = []
    for story in data.stories():
        story_id = _story_id(story)
        sentiment = str(_get(story, "sentiment", default="Neutral"))
        rows.append(
            rx.button(
                rx.grid(
                    rx.text(
                        _compact_timestamp(_get(story, "timestamp", "time", default="--:--")),
                        color=CYAN,
                    ),
                    rx.text(
                        str(_get(story, "headline", "title")),
                        color=TEXT,
                        text_align="left",
                    ),
                    rx.text(
                        sentiment[:3].upper(),
                        color=GREEN
                        if sentiment.lower() == "positive"
                        else RED
                        if sentiment.lower() == "negative"
                        else AMBER,
                        text_align="right",
                    ),
                    grid_template_columns="58px minmax(0, 1fr) 40px",
                    width="100%",
                    align_items="start",
                ),
                on_click=TerminalState.select_story(story_id),
                variant="surface",
                radius="none",
                box_shadow="none",
                width="100%",
                height="auto",
                min_height="42px",
                padding="5px 3px",
                border_bottom="1px solid #1d1d19",
                background=rx.cond(
                    TerminalState.selected_story == story_id, "#231c08", "transparent"
                ),
                font_family=MONO,
                font_size="10px",
                white_space="normal",
                _hover={"background": "#231c08"},
            )
        )
    return rx.vstack(*rows, spacing="0", width="100%")


def selected_story_detail() -> rx.Component:
    stories = list(data.stories())
    if not stories:
        return rx.text("NO STORIES", color=MUTED)
    result = _story_detail(stories[0])
    for story in reversed(stories):
        result = rx.cond(
            TerminalState.selected_story == _story_id(story), _story_detail(story), result
        )
    return result


def calendar_table() -> rx.Component:
    column_template = "82px 42px minmax(200px, 1fr) 72px 76px 76px"
    rows = []
    for event in data.calendar_events():
        importance = str(_get(event, "importance", "impact", default="Medium"))
        rows.append(
            rx.grid(
                rx.text(
                    _compact_timestamp(
                        _get(event, "time", "timestamp", default="--:--"), include_date=True
                    ),
                    color=CYAN,
                ),
                rx.text(str(_get(event, "country", "region", default="US")), color=AMBER),
                rx.text(str(_get(event, "event", "name", "title")), color=TEXT),
                rx.text(importance, color=RED if importance.lower() == "high" else AMBER),
                rx.text(str(_get(event, "consensus", "forecast", default="—")), text_align="right"),
                rx.text(str(_get(event, "prior", "previous", default="—")), text_align="right"),
                grid_template_columns=column_template,
                width="100%",
                padding="5px 2px",
                border_bottom="1px solid #1d1d19",
                font_family=MONO,
                font_size="10px",
            )
        )
    header = rx.grid(
        *[
            rx.text(label, color=MUTED, text_align="right" if index >= 4 else "left")
            for index, label in enumerate(
                ("TIME", "REGION", "EVENT", "IMPACT", "CONSENSUS", "PRIOR")
            )
        ],
        grid_template_columns=column_template,
        width="100%",
        padding="3px 2px",
        font_family=MONO,
        font_size="9px",
        border_bottom=f"1px solid {BORDER}",
    )
    return rx.box(
        rx.vstack(header, *rows, spacing="0", width="100%", min_width="650px"),
        width="100%",
        overflow_x="auto",
    )


def news_workspace() -> rx.Component:
    return rx.vstack(
        rx.grid(
            panel("Newswire", news_list(), subtitle="fictional headlines"),
            panel("Story detail", selected_story_detail()),
            columns=rx.breakpoints(initial="1", md="2"),
            gap="8px",
            width="100%",
        ),
        panel("Economic calendar", calendar_table(), subtitle=f"as of {AS_OF}"),
        spacing="2",
        width="100%",
    )


def workspace() -> rx.Component:
    return rx.box(
        rx.cond(
            TerminalState.workspace == "MARKETS",
            markets_workspace(),
            rx.cond(
                TerminalState.workspace == "SECURITY",
                security_workspace(),
                rx.cond(
                    TerminalState.workspace == "PORTFOLIO",
                    portfolio_workspace(),
                    rx.cond(TerminalState.workspace == "RISK", risk_workspace(), news_workspace()),
                ),
            ),
        ),
        width="100%",
        min_width="0",
    )


def context_rail() -> rx.Component:
    return rx.vstack(
        panel(
            "Context",
            rx.vstack(
                rx.text(TerminalState.workspace, color=AMBER, font_family=MONO, font_weight="900"),
                rx.text(
                    f"DES {TerminalState.selected_symbol}",
                    color=TEXT,
                    font_family=MONO,
                    font_size="11px",
                ),
                rx.text(TerminalState.view_status, color=MUTED, font_family=MONO, font_size="9px"),
                spacing="1",
                align="start",
            ),
        ),
        panel(
            "Chart readout",
            rx.cond(
                TerminalState.hovered.length() > 0,
                rx.vstack(
                    rx.text(
                        f"X  {TerminalState.hovered['x']}",
                        color=TEXT,
                        font_family=MONO,
                        font_size="10px",
                    ),
                    rx.text(
                        f"Y  {TerminalState.hovered['y']}",
                        color=TEXT,
                        font_family=MONO,
                        font_size="10px",
                    ),
                    spacing="1",
                    align="start",
                ),
                rx.text("HOVER A CHART POINT", color=MUTED, font_family=MONO, font_size="9px"),
            ),
        ),
        panel(
            "Quick functions",
            rx.vstack(
                terminal_button(
                    "DES AAPL", on_click=TerminalState.select_symbol("AAPL"), width="100%"
                ),
                terminal_button(
                    "PORTFOLIO", on_click=TerminalState.choose_workspace("PORTFOLIO"), width="100%"
                ),
                terminal_button(
                    "RISK MONITOR", on_click=TerminalState.choose_workspace("RISK"), width="100%"
                ),
                terminal_button(
                    "NEWSWIRE", on_click=TerminalState.choose_workspace("NEWS"), width="100%"
                ),
                spacing="1",
                width="100%",
            ),
        ),
        panel(
            "System",
            rx.vstack(
                rx.hstack(
                    rx.text("DATA"),
                    rx.text("SIMULATED", color=RED),
                    justify="between",
                    width="100%",
                ),
                rx.hstack(
                    rx.text("AS OF"), rx.text(AS_OF, color=TEXT), justify="between", width="100%"
                ),
                rx.hstack(
                    rx.text("STREAM"),
                    rx.text(
                        rx.cond(TerminalState.streaming, "LIVE", "IDLE"),
                        color=rx.cond(TerminalState.streaming, GREEN, MUTED),
                    ),
                    justify="between",
                    width="100%",
                ),
                terminal_button(
                    rx.cond(TerminalState.streaming, "STOP LIVE TAPE", "START LIVE TAPE"),
                    on_click=TerminalState.stream_quotes,
                    width="100%",
                ),
                spacing="1",
                width="100%",
                color=MUTED,
                font_family=MONO,
                font_size="9px",
            ),
        ),
        width="100%",
        spacing="2",
    )


def function_keys() -> rx.Component:
    keys = (
        ("F1", "MARKETS"),
        ("F2", "SECURITY"),
        ("F3", "PORTFOLIO"),
        ("F4", "RISK"),
        ("F5", "NEWS"),
    )
    return rx.hstack(
        *[
            rx.button(
                rx.hstack(
                    rx.text(key, color=INK, background=AMBER, padding="2px 4px", font_weight="900"),
                    rx.text(label, color=TEXT),
                    spacing="1",
                ),
                on_click=TerminalState.choose_workspace(label),
                variant="surface",
                radius="none",
                box_shadow="none",
                background=rx.cond(TerminalState.workspace == label, "#231c08", "transparent"),
                margin="0",
                flex_shrink="0",
                white_space="nowrap",
                min_height="27px",
                padding="2px 6px",
                border_right=f"1px solid {BORDER}",
                border_bottom=rx.cond(
                    TerminalState.workspace == label,
                    f"2px solid {AMBER}",
                    "2px solid transparent",
                ),
                font_family=MONO,
                font_size="9px",
                _hover={"background": "#231c08"},
                _focus_visible={"outline": f"2px solid {CYAN}", "outline_offset": "-2px"},
            )
            for key, label in keys
        ],
        terminal_button("DEV", on_click=TerminalState.toggle_developer, compact=True),
        width="100%",
        overflow_x="auto",
        spacing="0",
        background="#090a0a",
        border_top=f"1px solid {BORDER}",
        border_bottom=f"1px solid {BORDER}",
    )


def _source(obj: Any) -> str:
    fget = getattr(obj, "_fget", None)
    if fget is not None:
        builder = getattr(fget, BUILDER_ATTR, None)
        return inspect.getsource(builder if builder is not None else fget)
    handler = getattr(obj, "fn", None)
    return inspect.getsource(handler if handler is not None else obj)


def developer_drawer() -> rx.Component:
    source = "\n\n".join(
        _source(obj)
        for obj in (
            TerminalState.security_figure,
            TerminalState.risk_figure,
            TerminalState.stream_quotes,
        )
    )
    try:
        spec = json.dumps(
            charts.abbreviated_spec(
                charts.security_chart(
                    "AAPL",
                    range_key="3M",
                    overlays=("SMA 20", "VWAP"),
                    oscillator="RSI",
                )
            ),
            indent=2,
            default=str,
        )
    except (TypeError, ValueError):
        spec = "chart spec unavailable"
    return rx.cond(
        TerminalState.developer_open,
        rx.fragment(
            rx.box(
                on_click=TerminalState.toggle_developer,
                position="fixed",
                inset="0",
                background="rgba(0,0,0,0.68)",
                z_index="60",
            ),
            rx.box(
                rx.hstack(
                    rx.text("DEVELOPER CONSOLE", color=AMBER, font_family=MONO, font_weight="900"),
                    terminal_button("CLOSE", on_click=TerminalState.toggle_developer),
                    justify="between",
                    width="100%",
                    padding="8px",
                    border_bottom=f"1px solid {BORDER}",
                ),
                rx.hstack(
                    *[
                        state_button(
                            tab,
                            TerminalState.developer_tab == tab,
                            TerminalState.set_developer_tab(tab),
                        )
                        for tab in ("SOURCE", "STATE", "SPEC")
                    ],
                    padding="8px",
                    spacing="1",
                ),
                rx.box(
                    rx.cond(
                        TerminalState.developer_tab == "SOURCE",
                        rx.el.pre(source),
                        rx.cond(
                            TerminalState.developer_tab == "STATE",
                            rx.el.pre(TerminalState.state_snapshot),
                            rx.el.pre(spec),
                        ),
                    ),
                    padding="10px",
                    color="#d9f99d",
                    font_family=MONO,
                    font_size="10px",
                    line_height="1.45",
                    white_space="pre-wrap",
                    overflow="auto",
                    flex="1",
                ),
                position="fixed",
                right="0",
                top="0",
                bottom="0",
                width=rx.breakpoints(initial="100%", md="min(640px, 72vw)"),
                background=PANEL,
                border_left=f"1px solid {AMBER}",
                z_index="70",
                display="flex",
                flex_direction="column",
            ),
        ),
        rx.box(),
    )


def terminal_shell() -> rx.Component:
    return rx.box(
        rx.box(
            rx.box(
                rx.hstack(
                    rx.vstack(
                        rx.hstack(
                            rx.text(
                                "XY TERMINAL",
                                color=AMBER,
                                font_family=MONO,
                                font_size="18px",
                                font_weight="950",
                                white_space="nowrap",
                            ),
                            rx.text(
                                "MULTI-ASSET ANALYTICS",
                                color=MUTED,
                                font_family=MONO,
                                font_size="9px",
                                white_space="nowrap",
                                display=rx.breakpoints(initial="none", sm="block"),
                            ),
                            spacing="2",
                            align="center",
                        ),
                        rx.text(
                            "INDEPENDENT TERMINAL-STYLE DEMO · NO EXTERNAL MARKET FEED",
                            color=MUTED,
                            font_family=MONO,
                            font_size="8px",
                            white_space="nowrap",
                            display=rx.breakpoints(initial="none", md="block"),
                        ),
                        spacing="0",
                        align="start",
                        min_width="0",
                    ),
                    rx.spacer(),
                    rx.text(
                        f"AS OF {AS_OF}",
                        color=TEXT,
                        font_family=MONO,
                        font_size="9px",
                        white_space="nowrap",
                        flex_shrink="0",
                    ),
                    align="center",
                    width="100%",
                    padding="6px 8px",
                ),
                command_bar(),
                padding="0 8px 7px",
                background="#090a0a",
            ),
            ticker_tape(),
            position="sticky",
            top="0",
            z_index="40",
            background=INK,
        ),
        rx.grid(
            rx.box(
                rx.vstack(watchlist(), context_rail(), spacing="2", width="100%"),
                min_width="0",
                order=rx.breakpoints(initial="2", sm="1"),
                display=rx.breakpoints(initial="block", lg="none"),
                position=rx.breakpoints(initial="static", sm="sticky"),
                top="112px",
                max_height=rx.breakpoints(initial="none", sm="calc(100vh - 160px)"),
                overflow_y=rx.breakpoints(initial="visible", sm="auto"),
                scrollbar_width="thin",
            ),
            rx.box(
                watchlist(),
                min_width="0",
                order="1",
                display=rx.breakpoints(initial="none", lg="block"),
                position="sticky",
                top="112px",
            ),
            rx.box(
                workspace(),
                min_width="0",
                overflow="hidden",
                order=rx.breakpoints(initial="1", sm="2"),
            ),
            rx.box(
                context_rail(),
                min_width="0",
                order="3",
                display=rx.breakpoints(initial="none", lg="block"),
                position="sticky",
                top="112px",
            ),
            grid_template_columns=rx.breakpoints(
                initial="minmax(0, 1fr)",
                sm="180px minmax(0, 1fr)",
                lg="210px minmax(0, 1fr) 225px",
            ),
            gap="8px",
            width="100%",
            padding="8px",
            align_items="start",
            flex="1",
        ),
        rx.box(
            function_keys(),
            rx.hstack(
                rx.text(
                    TerminalState.command_status,
                    color=CYAN,
                    min_width="0",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
                rx.spacer(),
                rx.hstack(
                    rx.text("● LOCAL", color=GREEN, white_space="nowrap"),
                    rx.text(
                        "NO API KEY",
                        color=MUTED,
                        white_space="nowrap",
                        display=rx.breakpoints(initial="none", sm="block"),
                    ),
                    spacing="2",
                    flex_shrink="0",
                ),
                width="100%",
                padding="3px 8px",
                background="#080909",
                font_family=MONO,
                font_size="9px",
            ),
            position="sticky",
            bottom="0",
            z_index="40",
            background="#080909",
        ),
        developer_drawer(),
        background=INK,
        color=TEXT,
        min_height="100vh",
        width="100%",
        font_family=MONO,
        display="flex",
        flex_direction="column",
    )


def index() -> rx.Component:
    return terminal_shell()


__all__ = [
    "YIELD_CURVE_TOKEN",
    "context_rail",
    "developer_drawer",
    "index",
    "markets_workspace",
    "news_workspace",
    "portfolio_workspace",
    "risk_workspace",
    "security_workspace",
    "terminal_shell",
]
