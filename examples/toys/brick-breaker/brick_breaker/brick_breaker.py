"""Brick breaker on an xy heatmap gameboard.

The gameboard is a single `xy.heatmap` whose `z` matrix is rasterized from
state every tick on a fine cell grid, so game objects are decoupled from cell
size: bricks are multi-cell blocks, the ball is a small disc, and the paddle
is several ball-widths wide. The viewport is fixed (navigation disabled,
explicit axis domains), so the grid never pans or zooms. The paddle tracks the
mouse through the chart's structured `on_hover` payload, which reports the
cursor's data-space x coordinate — no clicks, no keyboard.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import reflex as rx
import reflex_xy

import xy

# --- Fine render grid (heatmap resolution) ---------------------------------
GW = 73  # cells across
GH = 96  # cells down

# --- Ball ------------------------------------------------------------------
BALL_R = 2.6  # radius, in cells (~5.2-cell diameter)

# --- Paddle ----------------------------------------------------------------
PADDLE_W = 22.0  # width in cells (~4 ball-widths)
PADDLE_Y0 = 2  # bottom edge (row)
PADDLE_Y1 = 6  # top edge (exclusive)
BALL_FLOOR = float(PADDLE_Y1)  # y-plane the ball bounces off the paddle top

# --- Bricks ----------------------------------------------------------------
BRICK_COLS_N = 9
BRICK_ROWS_N = 6
BRICK_W = 7  # cells wide
BRICK_H = 4  # cells tall
BRICK_GAP = 1
BRICK_X0 = 1  # left margin (cells)
BRICK_TOP_Y1 = GH - 3  # top edge (exclusive) of the topmost brick row

MAX_LEVEL = 3

# --- Cell values -> colormap stops (domain is fixed at (0, 8)) -------------
EMPTY = 0
BALL = 7
PADDLE = 8
# 0 empty, 1..6 brick rows, 7 ball, 8 paddle.
PALETTE = [
    "#0b1020",  # 0 empty board
    "#ff5252",  # 1 red
    "#ff9f43",  # 2 orange
    "#feca57",  # 3 yellow
    "#1dd1a1",  # 4 green
    "#54a0ff",  # 5 blue
    "#a55eea",  # 6 purple
    "#ffffff",  # 7 ball
    "#00d2d3",  # 8 paddle
]
DOMAIN = (0.0, 8.0)

# --- Physics ---------------------------------------------------------------
TICK = 0.033  # seconds between frames (~30 fps)
BALL_SPEED = 1.25  # cells per tick
MAX_VX = 1.5
MIN_VY = 0.5
PADDLE_ENGLISH = 0.85  # how much paddle offset steers the ball
START_LIVES = 3


def _brick_rect(r: int, c: int) -> tuple[int, int, int, int]:
    """(x0, x1, y0, y1) cell bounds of brick at logical row r, column c."""
    x0 = BRICK_X0 + c * (BRICK_W + BRICK_GAP)
    y1 = BRICK_TOP_Y1 - r * (BRICK_H + BRICK_GAP)
    return x0, x0 + BRICK_W, y1 - BRICK_H, y1


def _pattern_keep(level: int, r: int, c: int) -> bool:
    """Whether the brick at logical (row r from top, column c) exists on a level."""
    if level <= 1:
        return True  # solid wall
    if level == 2:
        return (r + c) % 2 == 0  # checkerboard
    # level 3+: centered pyramid, narrow at the top, widening downward.
    cmid = (BRICK_COLS_N - 1) / 2
    return abs(c - cmid) <= r + 0.5


def _level_bricks(level: int) -> list[int]:
    """A flat BRICK_ROWS_N*BRICK_COLS_N grid of brick color values (0 = empty)."""
    grid = [EMPTY] * (BRICK_ROWS_N * BRICK_COLS_N)
    for r in range(BRICK_ROWS_N):
        color = 1 + (r % 6)
        for c in range(BRICK_COLS_N):
            if _pattern_keep(level, r, c):
                grid[r * BRICK_COLS_N + c] = color
    return grid


class Game(rx.State):
    """All brick-breaker game state."""

    status: str = "ready"  # ready | playing | won | lost
    score: int = 0
    lives: int = START_LIVES
    level: int = 1
    bricks: list[int] = _level_bricks(1)

    paddle_x: float = GW / 2

    # Continuous ball position (read by the figure -> republishes each frame).
    ball_x: float = GW / 2
    ball_y: float = BALL_FLOOR + 8.0

    # Ball velocity + serve direction (backend only — never sent to client).
    _vx: float = 0.0
    _vy: float = 0.0
    _serve_left: bool = False

    # Persistent bricks-only raster (backend cache): rebuilt only when a brick
    # is destroyed or a level loads, never per frame. Each frame copies it and
    # stamps the paddle + ball on top (§ the copy keeps every heatmap upload a
    # stable snapshot, since the data plane serializes z off the event loop).
    _board: Any = None

    @reflex_xy.figure
    def board(self) -> xy.Chart:
        """Compose the frame: cached bricks raster + paddle + ball.

        The bricks layer is not rebuilt here — only copied — so each frame does
        just three cheap paints (copy, paddle, ball), and the copy makes the
        array a private snapshot the upload thread can serialize safely.
        """
        z = self._ensure_board().copy()

        # Paddle (wide block at the bottom).
        half = PADDLE_W / 2
        pl = max(0, int(round(self.paddle_x - half)))
        pr = min(GW, int(round(self.paddle_x + half)))
        z[PADDLE_Y0:PADDLE_Y1, pl:pr] = PADDLE

        # Ball (small disc drawn on top) while in play or waiting to launch.
        if self.status in ("ready", "playing"):
            self._paint_ball(z)

        return xy.heatmap_chart(
            xy.heatmap(z=z, colormap=PALETTE, domain=DOMAIN, opacity=1.0),
            xy.x_axis(show=False, domain=(-0.5, GW - 0.5)),
            xy.y_axis(show=False, domain=(-0.5, GH - 0.5)),
            xy.interaction_config(navigation=False, hover=True, click=False),
            xy.modebar(show=False),
            xy.tooltip(show=False),
            width="100%",
            height="100%",
        )

    def _paint_ball(self, z: np.ndarray) -> None:
        bx, by = self.ball_x, self.ball_y
        x0 = max(0, int(np.floor(bx - BALL_R)))
        x1 = min(GW, int(np.ceil(bx + BALL_R)) + 1)
        y0 = max(0, int(np.floor(by - BALL_R)))
        y1 = min(GH, int(np.ceil(by + BALL_R)) + 1)
        if x1 <= x0 or y1 <= y0:
            return
        ys, xs = np.ogrid[y0:y1, x0:x1]
        mask = (xs - bx) ** 2 + (ys - by) ** 2 <= (BALL_R + 0.3) ** 2
        block = z[y0:y1, x0:x1]
        block[mask] = BALL

    # --- bricks raster cache ----------------------------------------------
    def _raster_bricks(self) -> np.ndarray:
        """Paint the full bricks layer from the logical `bricks` grid."""
        board = np.zeros((GH, GW), dtype=np.float32)
        bricks = self.bricks
        for r in range(BRICK_ROWS_N):
            for c in range(BRICK_COLS_N):
                color = bricks[r * BRICK_COLS_N + c]
                if color:
                    x0, x1, y0, y1 = _brick_rect(r, c)
                    board[y0:y1, x0:x1] = color
        return board

    def _ensure_board(self) -> np.ndarray:
        """The cached bricks raster, rebuilt only if missing/stale."""
        board = self._board
        if board is None or board.shape != (GH, GW):
            board = self._raster_bricks()
            self._board = board
        return board

    # --- events ------------------------------------------------------------
    @rx.event
    def on_hover(self, payload: dict):
        """Align the paddle with the mouse's data-space x coordinate."""
        cursor = payload.get("cursor") if payload else None
        if not cursor:
            return
        data = cursor.get("data") or {}
        x = data.get("x")
        if x is None:
            return
        half = PADDLE_W / 2
        self.paddle_x = max(half, min(GW - half, float(x)))

    @rx.event
    def start(self):
        """Start (or restart) a game and kick off the tick loop."""
        if self.status == "playing":
            return
        if self.status in ("won", "lost"):
            self.score = 0
            self.lives = START_LIVES
            self.level = 1
            self.bricks = _level_bricks(1)
            self._board = None  # force the bricks raster to rebuild
        self.status = "playing"
        self._reset_ball()
        return Game.game_loop

    @rx.event(background=True)
    async def game_loop(self):
        """Advance the ball on a fixed cadence until the game ends."""
        while True:
            async with self:
                if self.status != "playing":
                    return
                self._advance()
            await asyncio.sleep(TICK)

    # --- physics (backend helpers) -----------------------------------------
    def _reset_ball(self):
        self.ball_x = self.paddle_x
        self.ball_y = BALL_FLOOR + 8.0
        angle = -0.5 if self._serve_left else 0.5
        self._vx = BALL_SPEED * angle
        self._vy = BALL_SPEED
        self._serve_left = not self._serve_left

    def _advance(self):
        bx, by = self.ball_x, self.ball_y
        nbx = bx + self._vx
        nby = by + self._vy

        # Left / right walls.
        if nbx < BALL_R:
            nbx = BALL_R
            self._vx = abs(self._vx)
        elif nbx > GW - 1 - BALL_R:
            nbx = GW - 1 - BALL_R
            self._vx = -abs(self._vx)

        # Ceiling.
        if nby > GH - 1 - BALL_R:
            nby = GH - 1 - BALL_R
            self._vy = -abs(self._vy)

        # Paddle top surface.
        if self._vy < 0 and (nby - BALL_R) <= BALL_FLOOR:
            half = PADDLE_W / 2
            if (self.paddle_x - half - BALL_R) <= nbx <= (self.paddle_x + half + BALL_R):
                nby = BALL_FLOOR + BALL_R
                self._vy = max(MIN_VY, abs(self._vy))
                offset = (nbx - self.paddle_x) / half
                self._vx = max(-MAX_VX, min(MAX_VX, self._vx + offset * PADDLE_ENGLISH))

        # Below the paddle with no catch -> lose a life.
        if nby < -BALL_R:
            self.ball_x, self.ball_y = nbx, nby
            self._lose_life()
            return

        nbx, nby = self._resolve_bricks(nbx, nby)

        self.ball_x = nbx
        self.ball_y = nby

        # Cleared the board? Advance a level or win the game (re-seeds the ball,
        # so it runs after committing the position above).
        if not any(self.bricks):
            self._advance_level()

    def _resolve_bricks(self, nbx: float, nby: float) -> tuple[float, float]:
        """Reflect off (and destroy) the first brick the ball overlaps."""
        bricks = self.bricks
        for r in range(BRICK_ROWS_N):
            for c in range(BRICK_COLS_N):
                i = r * BRICK_COLS_N + c
                if not bricks[i]:
                    continue
                x0, x1, y0, y1 = _brick_rect(r, c)
                # Expanded (Minkowski) rect for a circle of radius BALL_R.
                if not (x0 - BALL_R <= nbx <= x1 + BALL_R and y0 - BALL_R <= nby <= y1 + BALL_R):
                    continue
                # Minimal-translation axis: whichever penetration is smaller.
                pen_x = min(x1 + BALL_R - nbx, nbx - (x0 - BALL_R))
                pen_y = min(y1 + BALL_R - nby, nby - (y0 - BALL_R))
                if pen_x < pen_y:
                    self._vx = -self._vx
                    nbx += pen_x if nbx < (x0 + x1) / 2 else -pen_x
                else:
                    self._vy = -self._vy
                    nby += pen_y if nby < (y0 + y1) / 2 else -pen_y

                new_bricks = list(bricks)
                new_bricks[i] = EMPTY
                self.bricks = new_bricks
                self.score += 10
                # Incrementally erase just this brick from the cached raster,
                # instead of rebuilding the whole bricks layer.
                if self._board is not None:
                    self._board[y0:y1, x0:x1] = EMPTY
                return nbx, nby
        return nbx, nby

    def _advance_level(self):
        if self.level >= MAX_LEVEL:
            self.status = "won"
            return
        self.level += 1
        self.score += 100  # level-clear bonus
        self.bricks = _level_bricks(self.level)
        self._board = None  # force the bricks raster to rebuild for the new level
        self._reset_ball()

    def _lose_life(self):
        self.lives -= 1
        if self.lives <= 0:
            self.lives = 0
            self.status = "lost"
            return
        self._reset_ball()


# --- UI --------------------------------------------------------------------
def _stat(label: str, value: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="1", color_scheme="gray", weight="medium"),
        rx.text(value, size="6", weight="bold"),
        spacing="0",
        align="center",
    )


def _overlay() -> rx.Component:
    """Start / win / lose message shown over the board."""
    return rx.cond(
        Game.status != "playing",
        rx.center(
            rx.vstack(
                rx.heading(
                    rx.match(
                        Game.status,
                        ("won", "You win! 🎉"),
                        ("lost", "Game over"),
                        "Brick Breaker",
                    ),
                    size="7",
                    color="white",
                ),
                rx.text(
                    rx.match(
                        Game.status,
                        ("ready", f"Clear all {MAX_LEVEL} levels — move the mouse to aim."),
                        ("won", f"All levels cleared! Final score: {Game.score}"),
                        ("lost", f"Final score: {Game.score}"),
                        "",
                    ),
                    color="gray",
                ),
                rx.button(
                    rx.cond(Game.status == "ready", "Start", "Play again"),
                    on_click=Game.start,
                    size="3",
                ),
                spacing="4",
                align="center",
            ),
            position="absolute",
            inset="0",
            background="rgba(11, 16, 32, 0.72)",
            border_radius="12px",
        ),
    )


def index() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.hstack(
                _stat("Score", Game.score),
                _stat("Level", f"{Game.level} / {MAX_LEVEL}"),
                _stat("Lives", Game.lives),
                spacing="8",
                justify="center",
                width="100%",
            ),
            rx.box(
                reflex_xy.chart(
                    Game.board,
                    on_hover=Game.on_hover,
                    width="100%",
                    height="100%",
                ),
                _overlay(),
                position="relative",
                width="min(92vw, 460px)",
                height="min(118vw, 600px)",
                background="#0b1020",
                border_radius="12px",
                overflow="hidden",
                box_shadow="0 10px 40px rgba(0,0,0,0.4)",
            ),
            spacing="5",
            align="center",
        ),
        min_height="100vh",
        padding="4",
    )


app = rx.App()
app.add_page(index, title="Brick Breaker")
