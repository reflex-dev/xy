"""Small Reflex state surface for the XY terminal example.

Large market series live in :mod:`.data`'s module-level caches.  This state
only records the user's current terminal selections and small interaction
readouts; chart builders resolve the cached arrays when a figure var changes.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

import reflex as rx

import reflex_xy

from . import charts, data

WORKSPACES = ("MARKETS", "SECURITY", "PORTFOLIO", "RISK", "NEWS")
RANGES = ("1M", "3M", "6M", "1Y", "MAX")
RESOLUTIONS = ("1D", "1W")
OVERLAYS = ("SMA 20", "EMA 50", "Bollinger", "VWAP", "Anchored VWAP", "Volume Profile")
OSCILLATORS = ("None", "RSI", "MACD", "Stochastic")
DRAWINGS = (
    "None",
    "Long position",
    "Short position",
    "Forecast",
    "Bars pattern",
    "Ghost feed",
    "XABCD",
)
CONFIDENCE_LEVELS = ("95%", "99%")


def _number(value: str) -> float | None:
    """Parse a finite terminal input without allowing NaN/inf downstream."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _symbols() -> tuple[str, ...]:
    return tuple(str(symbol).upper() for symbol in data.instrument_symbols())


_TAPE_BASE = tuple(
    (
        str(row["symbol"]),
        float(row["last"]),
        float(row["change_percent"]),
        int(data.instrument(str(row["symbol"])).price_decimals),
    )
    for row in data.watchlist_rows()
)


def _tape_rows(step: int) -> list[dict[str, str]]:
    """Return ten compact, deterministic display rows for the live tape."""
    rows: list[dict[str, str]] = []
    for index, (symbol, baseline, base_change, decimals) in enumerate(_TAPE_BASE):
        wobble = math.sin((step + index * 2.0) / 5.0) * 0.0012
        wobble += math.sin((step + index * 7.0) / 13.0) * 0.0005
        last = baseline * (1.0 + wobble)
        change = base_change + wobble * 100.0
        rows.append(
            {
                "symbol": symbol,
                "last": f"{last:,.{decimals}f}",
                "change": f"{change:+.2f}%",
                "direction": "UP" if change >= 0 else "DOWN",
            }
        )
    return rows


def _ticket_prices(symbol: str, side: str) -> tuple[str, str, str]:
    quote = data.quote(symbol)
    decimals = data.instrument(symbol).price_decimals
    entry = float(quote.last)
    if side == "Long":
        stop, target = entry * 0.97, entry * 1.06
    else:
        stop, target = entry * 1.03, entry * 0.94
    return tuple(f"{value:.{decimals}f}" for value in (entry, stop, target))


_INITIAL_ENTRY, _INITIAL_STOP, _INITIAL_TARGET = _ticket_prices("AAPL", "Long")


class TerminalState(rx.State):
    """Interaction state for the single-page terminal shell."""

    workspace: str = "MARKETS"
    command: str = ""
    command_status: str = "READY — TRY MKTS, DES AAPL, PORT, RISK, NEWS, OR HELP"
    help_visible: bool = False

    selected_symbol: str = "AAPL"
    range_key: str = "6M"
    resolution: str = "1D"
    overlays: list[str] = ["SMA 20", "VWAP"]
    oscillator: str = "RSI"
    drawing: str = "Long position"

    hovered: dict[str, Any] = {}
    view_status: str = "FULL HISTORY"

    streaming: bool = False
    _stream_step: int = 35
    tape_quotes: list[dict[str, str]] = _tape_rows(35)

    ticket_side: str = "Long"
    ticket_entry: str = _INITIAL_ENTRY
    ticket_stop: str = _INITIAL_STOP
    ticket_target: str = _INITIAL_TARGET
    ticket_account: str = "100000"
    ticket_risk: str = "1.00"

    confidence_label: str = "95%"
    selected_scenario: str = "Equity selloff"
    selected_story: str = "N-001"

    developer_open: bool = False
    developer_tab: str = "SOURCE"

    def _raw_ticket(self) -> dict[str, Any]:
        return {
            "symbol": self.selected_symbol,
            "side": self.ticket_side.lower(),
            "entry": _number(self.ticket_entry),
            "stop": _number(self.ticket_stop),
            "target": _number(self.ticket_target),
            "account_size": _number(self.ticket_account),
            "risk_percent": _number(self.ticket_risk),
        }

    def _ticket_result(self) -> dict[str, Any]:
        payload = self._raw_ticket()
        if any(value is None for key, value in payload.items() if key not in {"side", "symbol"}):
            return {"valid": False, "error": "ENTER FINITE NUMERIC TICKET VALUES"}
        try:
            return dict(charts.ticket_metrics(payload))
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            return {"valid": False, "error": str(exc).upper()}

    def _reset_ticket_prices(self) -> None:
        self.ticket_entry, self.ticket_stop, self.ticket_target = _ticket_prices(
            self.selected_symbol, self.ticket_side
        )

    @rx.var
    def confidence(self) -> float:
        return 0.99 if self.confidence_label == "99%" else 0.95

    @rx.var
    def ticket_valid(self) -> bool:
        return bool(self._ticket_result().get("valid"))

    @rx.var
    def ticket_error(self) -> str:
        result = self._ticket_result()
        return "" if result.get("valid") else str(result.get("error") or "INVALID TICKET")

    @rx.var
    def ticket_risk_amount(self) -> str:
        value = self._ticket_result().get("risk_amount")
        return "—" if value is None else f"${float(value):,.2f}"

    @rx.var
    def ticket_position_size(self) -> str:
        value = self._ticket_result().get("quantity")
        return "—" if value is None else f"{float(value):,.2f}"

    @rx.var
    def ticket_reward_risk(self) -> str:
        value = self._ticket_result().get("risk_reward")
        return "—" if value is None else f"{float(value):.2f}×"

    @rx.var
    def state_snapshot(self) -> str:
        return (
            f"workspace={self.workspace}\n"
            f"symbol={self.selected_symbol} range={self.range_key} resolution={self.resolution}\n"
            f"overlays={','.join(self.overlays) or 'none'}\n"
            f"oscillator={self.oscillator} drawing={self.drawing}\n"
            f"confidence={self.confidence_label} scenario={self.selected_scenario}\n"
            f"streaming={self.streaming}"
        )

    @reflex_xy.figure
    def security_figure(self):
        ticket = self._raw_ticket() if self._ticket_result().get("valid") else None
        return charts.security_chart(
            self.selected_symbol,
            range_key=self.range_key,
            resolution=self.resolution,
            overlays=tuple(self.overlays),
            oscillator=self.oscillator,
            drawing=self.drawing,
            ticket=ticket,
        )

    @reflex_xy.figure
    def portfolio_figure(self):
        return charts.portfolio_performance_chart()

    @reflex_xy.figure
    def risk_figure(self):
        return charts.risk_distribution_chart(self.confidence)

    @reflex_xy.figure
    def market_pulse(self):
        return charts.market_pulse_chart()

    @rx.event
    def choose_workspace(self, workspace: str):
        target = workspace.strip().upper()
        if target in WORKSPACES:
            self.workspace = target
            self.command_status = f"{target} WORKSPACE"
            self.help_visible = False

    @rx.event
    def set_command(self, value: str):
        self.command = value

    def _execute_command(self) -> None:
        raw = self.command.strip()
        self.help_visible = False
        if not raw:
            self.command_status = "ENTER A COMMAND — HELP LISTS AVAILABLE FUNCTIONS"
            self.command = ""
            return
        parts = raw.upper().split()
        verb = parts[0]
        if verb == "MKTS" and len(parts) == 1:
            self.workspace = "MARKETS"
            self.command_status = "MKTS — GLOBAL MARKET MONITOR"
        elif verb == "DES" and len(parts) == 2:
            symbol = parts[1]
            if symbol in _symbols():
                self.selected_symbol = symbol
                self._reset_ticket_prices()
                self.workspace = "SECURITY"
                self.command_status = f"DES {symbol} — SECURITY DESCRIPTION"
            else:
                self.command_status = f"UNKNOWN SECURITY: {symbol}"
        elif verb in {"PORT", "RISK", "NEWS"} and len(parts) == 1:
            self.workspace = {"PORT": "PORTFOLIO", "RISK": "RISK", "NEWS": "NEWS"}[verb]
            self.command_status = f"{verb} — {self.workspace} WORKSPACE"
        elif verb == "HELP" and len(parts) == 1:
            self.help_visible = True
            self.command_status = "HELP — MKTS · DES <SYMBOL> · PORT · RISK · NEWS"
        else:
            self.command_status = f"UNKNOWN COMMAND: {raw.upper()} — TYPE HELP"
        self.command = ""

    @rx.event
    def execute_command(self):
        self._execute_command()

    @rx.event
    def command_key(self, key: str):
        if key == "Enter":
            self._execute_command()

    @rx.event
    def select_symbol(self, symbol: str):
        candidate = symbol.upper()
        if candidate not in _symbols():
            self.command_status = f"UNKNOWN SECURITY: {candidate}"
            return
        self.selected_symbol = candidate
        self._reset_ticket_prices()
        self.workspace = "SECURITY"
        self.command_status = f"DES {candidate} — SECURITY DESCRIPTION"

    @rx.event
    def set_range_key(self, value: str):
        if value in RANGES:
            self.range_key = value

    @rx.event
    def set_resolution(self, value: str):
        if value in RESOLUTIONS:
            self.resolution = value

    @rx.event
    def toggle_overlay(self, overlay: str):
        if overlay not in OVERLAYS:
            return
        if overlay in self.overlays:
            self.overlays = [item for item in self.overlays if item != overlay]
        else:
            self.overlays = [*self.overlays, overlay]

    @rx.event
    def set_oscillator(self, value: str):
        if value in OSCILLATORS:
            self.oscillator = value

    @rx.event
    def set_drawing(self, value: str):
        if value in DRAWINGS:
            self.drawing = value
            if value in {"Long position", "Short position"}:
                self.ticket_side = "Long" if value == "Long position" else "Short"
                self._reset_ticket_prices()

    @rx.event
    def set_ticket_side(self, value: str):
        if value in {"Long", "Short"}:
            self.ticket_side = value
            self._reset_ticket_prices()
            if self.drawing in {"Long position", "Short position"}:
                self.drawing = f"{value} position"

    @rx.event
    def set_ticket_entry(self, value: str):
        self.ticket_entry = value

    @rx.event
    def set_ticket_stop(self, value: str):
        self.ticket_stop = value

    @rx.event
    def set_ticket_target(self, value: str):
        self.ticket_target = value

    @rx.event
    def set_ticket_account(self, value: str):
        self.ticket_account = value

    @rx.event
    def set_ticket_risk(self, value: str):
        self.ticket_risk = value

    @rx.event
    def drilldown_position(self, symbol: str):
        self.selected_symbol = symbol.upper()
        self._reset_ticket_prices()
        self.workspace = "SECURITY"
        self.command_status = f"PORT → DES {self.selected_symbol}"

    @rx.event
    def set_confidence(self, value: str):
        if value in CONFIDENCE_LEVELS:
            self.confidence_label = value

    @rx.event
    def set_scenario(self, value: str):
        self.selected_scenario = value

    @rx.event
    def select_story(self, story_id: str):
        self.selected_story = story_id

    @rx.event
    def toggle_developer(self):
        self.developer_open = not self.developer_open

    @rx.event
    def set_developer_tab(self, tab: str):
        if tab in {"SOURCE", "STATE", "SPEC"}:
            self.developer_tab = tab

    @rx.event
    def on_chart_hover(self, event: dict[str, Any]):
        """Reduce the structured hover payload to a compact terminal readout."""
        if not event.get("active"):
            self.hovered = {}
            return
        points = event.get("points") or []
        point = points[0] if points else {}
        row = point.get("row") or {}
        cursor = (event.get("cursor") or {}).get("data") or {}
        x_axis = str(point.get("x_axis") or "x")
        y_axis = str(point.get("y_axis") or "y")
        self.hovered = {
            "x": row.get("x", cursor.get(x_axis, "—")),
            "y": row.get("y", cursor.get(y_axis, "—")),
            "trace": point.get("trace", "cursor"),
        }

    @rx.event
    def on_chart_view(self, event: reflex_xy.ViewChangeEvent):
        x_domain = event.get("x_domain") or []
        if len(x_domain) == 2:
            self.view_status = f"VIEW {float(x_domain[0]):.2f} → {float(x_domain[1]):.2f}"
        else:
            self.view_status = "VIEW UPDATED"

    @rx.event(background=True)
    async def stream_quotes(self):
        """Start/stop the single market-pulse producer for this state token."""
        async with self:
            if self.streaming:
                self.streaming = False
                return
            self.streaming = True
            token = self.market_pulse
        while True:
            async with self:
                if not self.streaming or token != self.market_pulse:
                    break
                self._stream_step += 1
                step = self._stream_step
                self.tape_quotes = _tape_rows(step)
            value = 100.0 + math.sin(step / 3.25) * 0.8 + math.sin(step / 11.0) * 1.4
            reflex_xy.append(token, x=[float(step)], y=[float(value)])
            await asyncio.sleep(0.8)


# A short alias keeps the example approachable in live notebooks and avoids
# breaking links that imported the former showcase's state class.
Demo = TerminalState


__all__ = [
    "CONFIDENCE_LEVELS",
    "DRAWINGS",
    "OSCILLATORS",
    "OVERLAYS",
    "RANGES",
    "RESOLUTIONS",
    "WORKSPACES",
    "Demo",
    "TerminalState",
]
