"""Live flight tracker: every airborne aircraft on Earth, in a Reflex app.

Default (``XY_FLIGHTS_MODE=world``): a background task polls OpenSky's
anonymous ``/states/all`` for the global picture (~12-15k aircraft) and
republishes an ``@reflex_xy.figure`` scatter each cycle — positions colored
by altitude, sized by ground speed, with per-aircraft trails, over the whole
Natural Earth 50m coastline + borders (~80k points) drawn with
``xy.segments``. Every cycle re-encodes and re-ships the full figure
(hundreds of thousands of segments, several MB of binary columns) while the
client keeps 60fps pan/zoom — that throughput is the point of the page.
Clicking an aircraft follows it; box-selecting cross-filters the histogram.

``XY_FLIGHTS_MODE=region`` switches to the adsb.fi open-data API: one 250 nm
circle (default: central Europe, ~900 aircraft), 1-second-capable cadence.

If the live API is unreachable the page falls back to bundled real captures:
region mode cycles ten recorded frames; world mode dead-reckons a single
14k-aircraft OpenSky capture forward along each aircraft's track at its
ground speed, so the world keeps moving with a ~270KB asset.
``data/regenerate.py`` rebuilds every bundled asset.

The latest frame and per-aircraft trails live in module globals keyed only by
the ``frame_rev`` state var — figure builders stay cheap and state stays a
few scalars. A fresh backend worker that has never polled falls back to the
replay seed, so rebuild-on-miss stays deterministic.
"""

from __future__ import annotations

import asyncio
import gzip
import itertools
import json
import os
import urllib.request
from functools import lru_cache
from pathlib import Path

import numpy as np
import reflex as rx
import reflex_xy

import xy

from .ui import code_accordion, kv, nav, section

DATA_DIR = Path(__file__).parent / "data"

# "world" = OpenSky /states/all, the whole planet at once. "region" = adsb.fi,
# one 250 nm circle at up-to-1s cadence.
WORLD = os.environ.get("XY_FLIGHTS_MODE", "world") != "region"

# Region-mode query circle (adsb.fi caps the radius at 250 nm). Override via
# env, e.g. XY_FLIGHTS_CENTER="40.64,-73.78" for JFK — then regenerate the
# bundled basemap/replay for that region with data/regenerate.py.
_center = os.environ.get("XY_FLIGHTS_CENTER", "50.03,8.57").split(",")
CENTER_LAT, CENTER_LON = float(_center[0]), float(_center[1])
RADIUS_NM = int(os.environ.get("XY_FLIGHTS_RADIUS", "250"))
REGION_URL = f"https://opendata.adsb.fi/api/v2/lat/{CENTER_LAT}/lon/{CENTER_LON}/dist/{RADIUS_NM}"
WORLD_URL = "https://opensky-network.org/api/states/all"

# Cadence. Region: adsb.fi's documented limit is 1 request/second and its feed
# refreshes about once a second — XY_FLIGHTS_POLL=1 is the useful floor.
# World: OpenSky bills anonymous callers 4 credits per global snapshot from a
# 400/day budget (100 calls), so the default spends them slowly; on a 429 the
# page falls back to the dead-reckoned replay.
_default_poll = "15" if WORLD else "3"
POLL_SECONDS = max(1.0, float(os.environ.get("XY_FLIGHTS_POLL", _default_poll)))
REPLAY_SECONDS = 3.0
# Positions kept per aircraft. World trails are shorter: ~14k aircraft x
# trail segments x 5 columns is the dominant share of each republish.
TRAIL_LEN = 12 if WORLD else 24
ALT_DOMAIN = (0.0, 45_000.0)  # ft; fixed so colors are stable across frames

# View window. Region: ±7° latitude, ±21° longitude — 3:1 to roughly offset
# equirectangular stretch at 50°N in a wide chart. World: everything between
# the polar dead zones.
VIEW_LAT = (-60.0, 75.0) if WORLD else (CENTER_LAT - 7.0, CENTER_LAT + 7.0)
VIEW_LON = (-180.0, 180.0) if WORLD else (CENTER_LON - 21.0, CENTER_LON + 21.0)
BASEMAP_FILE = "basemap_world.json.gz" if WORLD else "basemap_eu.json.gz"
PLACE = "worldwide" if WORLD else "over central Europe"


# --- data sources -----------------------------------------------------------


def _columns(aircraft: list[dict]) -> dict:
    """tar1090-style aircraft list -> columnar frame. ``alt_baro`` is the
    string ``"ground"`` for taxiing aircraft; those become 0 ft."""
    cols: dict[str, list] = {
        k: [] for k in ("hex", "flight", "type", "lat", "lon", "alt", "gs", "track")
    }
    for a in aircraft:
        lat, lon = a.get("lat"), a.get("lon")
        if lat is None or lon is None:
            continue
        alt = a.get("alt_baro")
        cols["hex"].append(a.get("hex", ""))
        cols["flight"].append((a.get("flight") or "").strip())
        cols["type"].append(a.get("t", ""))
        cols["lat"].append(float(lat))
        cols["lon"].append(float(lon))
        cols["alt"].append(float(alt) if isinstance(alt, (int, float)) else 0.0)
        cols["gs"].append(float(a.get("gs") or 0.0))
        cols["track"].append(float(a.get("track") or 0.0))
    return {
        "hex": cols["hex"],
        "flight": cols["flight"],
        "type": cols["type"],
        "lat": np.asarray(cols["lat"]),
        "lon": np.asarray(cols["lon"]),
        "alt": np.asarray(cols["alt"]),
        "gs": np.asarray(cols["gs"]),
        "track": np.asarray(cols["track"]),
    }


def _world_columns(states: list[list]) -> dict:
    """OpenSky ``/states/all`` rows -> columnar frame (SI units -> ft/kt)."""
    cols: dict[str, list] = {
        k: [] for k in ("hex", "flight", "type", "lat", "lon", "alt", "gs", "track")
    }
    for s in states:
        lon, lat = s[5], s[6]
        if lon is None or lat is None:
            continue
        on_ground, alt_m = bool(s[8]), s[7]
        cols["hex"].append(s[0] or "")
        cols["flight"].append((s[1] or "").strip())
        cols["type"].append("")  # OpenSky states carry no airframe type
        cols["lat"].append(float(lat))
        cols["lon"].append(float(lon))
        cols["alt"].append(
            0.0 if on_ground or not isinstance(alt_m, (int, float)) else float(alt_m) * 3.28084
        )
        cols["gs"].append(float(s[9] or 0.0) * 1.94384)
        cols["track"].append(float(s[10] or 0.0))
    return {
        "hex": cols["hex"],
        "flight": cols["flight"],
        "type": cols["type"],
        "lat": np.asarray(cols["lat"]),
        "lon": np.asarray(cols["lon"]),
        "alt": np.asarray(cols["alt"]),
        "gs": np.asarray(cols["gs"]),
        "track": np.asarray(cols["track"]),
    }


def fetch_live() -> dict:
    """One live frame — the whole planet (world) or one circle (region)."""
    url = WORLD_URL if WORLD else REGION_URL
    req = urllib.request.Request(url, headers={"User-Agent": "xy-reflex-example"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.load(resp)
    if WORLD:
        return _world_columns(payload.get("states") or [])
    return _columns(payload.get("aircraft", []))


def _decode_frames(name: str) -> list[dict]:
    raw = json.loads(gzip.decompress((DATA_DIR / name).read_bytes()))
    return [
        {
            "hex": f["hex"],
            "flight": f["flight"],
            "type": f["type"],
            "lat": np.asarray(f["lat"], dtype=np.float64),
            "lon": np.asarray(f["lon"], dtype=np.float64),
            "alt": np.asarray(f["alt"], dtype=np.float64),
            "gs": np.asarray(f["gs"], dtype=np.float64),
            "track": np.asarray(f["track"], dtype=np.float64),
        }
        for f in raw["frames"]
    ]


@lru_cache(maxsize=1)
def _replay_frames() -> list[dict]:
    return _decode_frames("replay_eu.json.gz")


@lru_cache(maxsize=1)
def _world_seed() -> dict:
    return _decode_frames("replay_world.json.gz")[0]


def _replay_frame(i: int) -> dict:
    """Offline frame ``i``. Region mode cycles ten recorded frames; world
    mode dead-reckons the single bundled capture: each aircraft advances
    along its recorded track at its recorded ground speed."""
    if not WORLD:
        frames = _replay_frames()
        return frames[i % len(frames)]
    seed = _world_seed()
    hours = (i * REPLAY_SECONDS) / 3600.0
    dist_deg = seed["gs"] * hours / 60.0  # kt -> nm -> degrees latitude
    rad = np.radians(seed["track"])
    lat = seed["lat"] + dist_deg * np.cos(rad)
    coslat = np.maximum(np.cos(np.radians(np.clip(lat, -85.0, 85.0))), 0.05)
    lon = seed["lon"] + dist_deg * np.sin(rad) / coslat
    lon = (lon + 180.0) % 360.0 - 180.0
    return {**seed, "lat": lat, "lon": lon}


@lru_cache(maxsize=1)
def _basemap() -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """Natural Earth 50m coastline + land borders as segment endpoint arrays."""
    raw = json.loads(gzip.decompress((DATA_DIR / BASEMAP_FILE).read_bytes()))
    out = {}
    for kind in ("coast", "borders"):
        x0, y0, x1, y1 = [], [], [], []
        for poly in raw[kind]:
            pts = np.asarray(poly, dtype=np.float64)
            x0.append(pts[:-1, 0])
            y0.append(pts[:-1, 1])
            x1.append(pts[1:, 0])
            y1.append(pts[1:, 1])
        out[kind] = tuple(np.concatenate(a) for a in (x0, y0, x1, y1))
    return out


# --- latest frame + trails (module state, keyed by the frame_rev var) -------

_latest: dict | None = None
_trails: dict[str, list[tuple[float, float, float]]] = {}  # hex -> [(lon, lat, alt)]


def _current_frame() -> dict:
    return _latest if _latest is not None else _replay_frame(0)


def _advance(frame: dict) -> None:
    """Install a new frame and extend/prune the per-aircraft trails."""
    global _latest
    _latest = frame
    seen = set(frame["hex"])
    rows = zip(frame["hex"], frame["lon"], frame["lat"], frame["alt"], strict=True)
    for h, lon, lat, alt in rows:
        _trails.setdefault(h, []).append((float(lon), float(lat), float(alt)))
        del _trails[h][:-TRAIL_LEN]
    for h in [h for h in _trails if h not in seen]:
        del _trails[h]


def _trail_segments() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x0, y0, x1, y1, alt = [], [], [], [], []
    for pts in _trails.values():
        for (lon0, lat0, _), (lon1, lat1, a1) in itertools.pairwise(pts):
            if abs(lon1 - lon0) > 90.0:  # antimeridian hop; don't smear the map
                continue
            x0.append(lon0)
            y0.append(lat0)
            x1.append(lon1)
            y1.append(lat1)
            alt.append(a1)
    return tuple(np.asarray(a) for a in (x0, y0, x1, y1, alt))


# --- state ------------------------------------------------------------------


class Flights(rx.State):
    """Scalars only; the frame itself stays server-side in module globals."""

    polling: bool = False
    source: str = "idle"  # "adsb.fi live" | "bundled replay" | "idle"
    frame_rev: int = 0
    n_aircraft: int = 0
    followed_hex: str = ""
    followed: dict = {}
    sel_active: bool = False
    sel_lon0: float = 0.0
    sel_lon1: float = 0.0
    sel_lat0: float = 0.0
    sel_lat1: float = 0.0
    sel_note: str = "box-select a region to filter the histogram"

    @reflex_xy.figure
    def sky(self) -> xy.Chart:
        _ = self.frame_rev  # depend on the poll cycle
        frame = _current_frame()
        base = _basemap()
        marks = [
            xy.segments(*base["coast"], color="#64748b", width=1.1, opacity=0.7),
            xy.segments(*base["borders"], color="#94a3b8", width=0.9, opacity=0.55),
        ]
        tx0, ty0, tx1, ty1, talt = _trail_segments()
        if tx0.size:
            marks.append(
                xy.segments(
                    tx0,
                    ty0,
                    tx1,
                    ty1,
                    color=talt,
                    colormap="turbo",
                    domain=ALT_DOMAIN,
                    width=1.0,
                    opacity=0.35,
                )
            )
        marks.append(
            xy.scatter(
                frame["lon"],
                frame["lat"],
                color=frame["alt"],
                colormap="turbo",
                color_domain=ALT_DOMAIN,
                size=frame["gs"],
                size_range=(2.5, 7.0),
                opacity=0.9,
                density=False,
            )
        )
        if self.followed_hex and self.followed_hex in frame["hex"]:
            i = frame["hex"].index(self.followed_hex)
            marks.append(
                xy.scatter(
                    frame["lon"][i : i + 1],
                    frame["lat"][i : i + 1],
                    color="#f43f5e",
                    opacity=0.25,
                    size=14.0,
                    stroke="#f43f5e",
                    stroke_width=2.0,
                )
            )
        return xy.scatter_chart(
            *marks,
            xy.interaction_config(hover=True, click=True),
            xy.x_axis(label="longitude", domain=VIEW_LON),
            xy.y_axis(label="latitude", domain=VIEW_LAT),
            title=f"{self.n_aircraft} aircraft · {self.source}",
            width="100%",
            height=520,
        )

    @reflex_xy.figure
    def altitudes(self) -> xy.Chart:
        _ = self.frame_rev
        frame = _current_frame()
        alt, lon, lat = frame["alt"], frame["lon"], frame["lat"]
        airborne = alt > 0.0
        if self.sel_active:
            airborne &= (
                (lon >= self.sel_lon0)
                & (lon <= self.sel_lon1)
                & (lat >= self.sel_lat0)
                & (lat <= self.sel_lat1)
            )
        label = "selection" if self.sel_active else "all airborne"
        return xy.histogram_chart(
            xy.histogram(alt[airborne], bins=45, color="#7c3aed"),
            xy.x_axis(label=f"barometric altitude, ft ({label})", format=",.0f"),
            title=f"altitude distribution — {int(airborne.sum())} aircraft",
            width="100%",
            height=260,
        )

    @reflex_xy.figure
    def follow(self) -> xy.Chart:
        _ = self.frame_rev
        trail = _trails.get(self.followed_hex, [])
        if len(trail) < 2:
            title = "click an aircraft on the map to follow it"
            alt = np.array([0.0])
            t = np.array([0.0])
        else:
            info = self.followed
            title = (
                f"{info.get('callsign') or self.followed_hex} ({info.get('type') or '?'}) "
                f"— altitude trail"
            )
            alt = np.asarray([p[2] for p in trail])
            t = np.arange(len(trail), dtype=np.float64) - (len(trail) - 1)
        return xy.line_chart(
            xy.line(t, alt, color="#f43f5e", width=2.0),
            xy.x_axis(label="poll cycles ago"),
            xy.y_axis(label="altitude (ft)", format=",.0f"),
            title=title,
            width="100%",
            height=260,
        )

    @rx.event
    def on_click(self, event: reflex_xy.PointClickEvent):
        # Match by nearest aircraft to the clicked f64 data coords instead of
        # trusting trace/row bookkeeping across the multi-mark figure.
        frame = _current_frame()
        if not frame["hex"]:
            return
        data = event.get("data", {})
        lon, lat = float(data.get("x", 0.0)), float(data.get("y", 0.0))
        d2 = (frame["lon"] - lon) ** 2 + (frame["lat"] - lat) ** 2
        i = int(np.argmin(d2))
        if d2[i] > 0.5**2:  # clicked empty sky / basemap
            return
        self.followed_hex = frame["hex"][i]
        self.followed = {
            "callsign": frame["flight"][i],
            "type": frame["type"][i],
            "alt": float(frame["alt"][i]),
            "gs": float(frame["gs"][i]),
        }

    @rx.event
    def unfollow(self):
        self.followed_hex = ""
        self.followed = {}

    @rx.event
    def on_select(self, event: reflex_xy.SelectEndEvent):
        selection = event.get("selection", {})
        bounds = selection.get("data_bounds") or {}
        if not selection.get("cleared") and bounds.get("x0") is not None:
            self.sel_lon0 = float(bounds["x0"])
            self.sel_lon1 = float(bounds["x1"])
            self.sel_lat0 = float(bounds["y0"])
            self.sel_lat1 = float(bounds["y1"])
            self.sel_active = True
            self.sel_note = f"{int(selection.get('total_count') or 0):,} aircraft in the box"
        else:
            self.sel_active = False
            self.sel_note = "selection cleared"

    @rx.event(background=True)
    async def poll(self):
        """Toggleable poll loop: live API first, bundled replay on failure."""
        async with self:
            if self.polling:
                self.polling = False
                self.source = "idle"
                return
            self.polling = True
        replay_i = 0
        while True:
            try:
                frame = await asyncio.to_thread(fetch_live)
                source, wait = ("opensky live" if WORLD else "adsb.fi live"), POLL_SECONDS
            except Exception:
                frame = _replay_frame(replay_i)
                replay_i += 1
                source, wait = "bundled replay", REPLAY_SECONDS
            _advance(frame)
            async with self:
                if not self.polling:
                    break
                self.source = source
                self.n_aircraft = len(frame["hex"])
                self.frame_rev += 1
            await asyncio.sleep(wait)


# --- layout -----------------------------------------------------------------


def sky_view() -> rx.Component:
    return rx.vstack(
        reflex_xy.chart(
            Flights.sky,
            on_point_click=Flights.on_click,
            on_select_end=Flights.on_select,
            height="520px",
            id="sky",
        ),
        rx.hstack(
            rx.button(
                rx.cond(Flights.polling, "stop", "start tracking"),
                on_click=Flights.poll,
                id="poll-btn",
            ),
            rx.button("unfollow", on_click=Flights.unfollow, variant="soft"),
            kv(
                "followed",
                rx.cond(
                    Flights.followed_hex != "",
                    f"{Flights.followed['callsign']} · {Flights.followed['type']} · "
                    f"{Flights.followed['alt']} ft · {Flights.followed['gs']} kt",
                    "click an aircraft",
                ),
            ),
            spacing="3",
            align="center",
        ),
        width="100%",
        spacing="3",
    )


def panels_view() -> rx.Component:
    return rx.vstack(
        rx.grid(
            reflex_xy.chart(Flights.follow, height="260px", id="follow"),
            reflex_xy.chart(Flights.altitudes, height="260px", id="altitudes"),
            columns="2",
            gap="1rem",
            width="100%",
        ),
        rx.text(Flights.sel_note, size="2", color_scheme="gray"),
        width="100%",
        spacing="2",
    )


def page() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.heading(f"live flights {PLACE}", size="8"),
            nav("flights"),
            rx.text(
                (
                    "Every airborne aircraft OpenSky can see — the whole planet, "
                    "republished through a figure var every cycle. Color is "
                    "altitude, size is ground speed. Falls back to dead-reckoning "
                    "a bundled real capture when the API is unreachable."
                    if WORLD
                    else "Real ADS-B positions from the adsb.fi open-data network, "
                    "republished through a figure var every few seconds. Color is "
                    "altitude, size is ground speed. Falls back to a bundled real "
                    "capture when the API is unreachable."
                ),
                color_scheme="gray",
                size="3",
            ),
            section(
                "1 · The sky",
                (
                    "~14,000 aircraft worldwide with trails, over the full Natural "
                    "Earth 50m coastline and borders (~80k points of xy.segments) — "
                    "every poll cycle rebuilds and re-ships the whole figure as "
                    "binary columns. Pan/zoom stays smooth throughout; the viewport "
                    "survives each republish. Click a plane to follow it; "
                    "shift-drag to box-select."
                    if WORLD
                    else "~900 aircraft in a 250 nm circle, over a Natural Earth "
                    "coastline drawn with xy.segments. Pan/zoom freely — the "
                    "viewport survives each republish. Click a plane to follow it; "
                    "shift-drag to box-select."
                ),
                sky_view(),
                code_accordion(Flights.sky, Flights.poll, Flights.on_click, sky_view),
            ),
            section(
                "2 · Follow + cross-filter",
                "Left: the followed aircraft's altitude trail, rebuilt from its "
                "recent frames. Right: altitude histogram of the current frame, "
                "cross-filtered by the map's box-selection.",
                panels_view(),
                code_accordion(Flights.follow, Flights.altitudes, Flights.on_select),
            ),
            spacing="5",
            width="100%",
        ),
        size="4",
        padding_y="28px",
    )
