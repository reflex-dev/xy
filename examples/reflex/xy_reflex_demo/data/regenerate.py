"""Rebuild the flights page's bundled assets (stdlib only).

* ``basemap_world.json.gz`` / ``basemap_eu.json.gz`` — Natural Earth 50m
  coastline + land-border polylines (whole world at 2 decimals / regional
  clip at 3 decimals).
* ``replay_world.json.gz`` — ONE full OpenSky ``/states/all`` capture; the
  app dead-reckons it forward for offline motion.
* ``replay_eu.json.gz`` — ten real ADS-B frames captured from adsb.fi.

Run from anywhere::

    python3 examples/reflex/xy_reflex_demo/data/regenerate.py --world
    python3 examples/reflex/xy_reflex_demo/data/regenerate.py \
        [--center LAT,LON] [--radius NM] [--frames N] [--interval SECONDS]

Re-centering (e.g. ``--center 40.64,-73.78`` for the US east coast) rebuilds
the regional assets for that region; set ``XY_FLIGHTS_CENTER`` to the same
value when running the app (with ``XY_FLIGHTS_MODE=region``).
"""

from __future__ import annotations

import argparse
import gzip
import json
import time
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent
NE_BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson"
NE_LAYERS = {
    "coast": "ne_50m_coastline.geojson",
    "borders": "ne_50m_admin_0_boundary_lines_land.geojson",
}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "xy-reflex-example"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _clip(geojson: dict, bbox: tuple[float, float, float, float]) -> list[list[list[float]]]:
    lon0, lat0, lon1, lat1 = bbox
    polys: list[list[list[float]]] = []
    for feat in geojson["features"]:
        g = feat["geometry"]
        if g["type"] not in ("LineString", "MultiLineString"):
            continue
        lines = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        for coords in lines:
            cur: list[list[float]] = []
            for lon, lat in coords:
                if lon0 <= lon <= lon1 and lat0 <= lat <= lat1:
                    cur.append([round(lon, 3), round(lat, 3)])
                else:
                    if len(cur) > 1:
                        polys.append(cur)
                    cur = []
            if len(cur) > 1:
                polys.append(cur)
    return polys


def build_basemap(center: tuple[float, float]) -> None:
    lat, lon = center
    # view box (±7° lat, ±21° lon) plus a margin so pans keep coastline
    bbox = (lon - 22.5, lat - 9.0, lon + 22.5, lat + 9.0)
    out = {"bbox": [bbox[0], bbox[1], bbox[2], bbox[3]]}
    for kind, name in NE_LAYERS.items():
        print(f"downloading {name} ...")
        out[kind] = _clip(json.loads(_get(f"{NE_BASE}/{name}")), bbox)
        print(f"  {kind}: {len(out[kind])} polylines")
    path = DATA_DIR / "basemap_eu.json.gz"
    path.write_bytes(gzip.compress(json.dumps(out, separators=(",", ":")).encode()))
    print(f"wrote {path} ({path.stat().st_size:,} bytes)")


def build_replay(center: tuple[float, float], radius: int, frames: int, interval: float) -> None:
    lat, lon = center
    url = f"https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{radius}"
    captured = []
    for i in range(frames):
        if i:
            time.sleep(interval)
        payload = json.loads(_get(url))
        cols: dict[str, list] = {
            k: [] for k in ("hex", "flight", "type", "lat", "lon", "alt", "gs", "track")
        }
        for a in payload.get("aircraft", []):
            if a.get("lat") is None or a.get("lon") is None:
                continue
            alt = a.get("alt_baro")
            cols["hex"].append(a.get("hex", ""))
            cols["flight"].append((a.get("flight") or "").strip())
            cols["type"].append(a.get("t", ""))
            cols["lat"].append(round(float(a["lat"]), 4))
            cols["lon"].append(round(float(a["lon"]), 4))
            cols["alt"].append(float(alt) if isinstance(alt, (int, float)) else 0.0)
            cols["gs"].append(round(float(a.get("gs") or 0.0), 1))
            cols["track"].append(round(float(a.get("track") or 0.0), 1))
        captured.append({"now": payload.get("now"), **cols})
        print(f"frame {i}: {len(cols['hex'])} aircraft")
    out = {"center": [lat, lon], "radius_nm": radius, "frames": captured}
    path = DATA_DIR / "replay_eu.json.gz"
    path.write_bytes(gzip.compress(json.dumps(out, separators=(",", ":")).encode()))
    print(f"wrote {path} ({path.stat().st_size:,} bytes)")


def build_world() -> None:
    """World basemap (2dp, lat ±85) + one OpenSky global capture."""
    out: dict = {"bbox": [-180, -85, 180, 85]}
    for kind, name in NE_LAYERS.items():
        print(f"downloading {name} ...")
        geo = json.loads(_get(f"{NE_BASE}/{name}"))
        polys = []
        for feat in geo["features"]:
            g = feat["geometry"]
            if g["type"] not in ("LineString", "MultiLineString"):
                continue
            lines = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
            for coords in lines:
                cur = []
                for lon, lat in coords:
                    if -85.0 <= lat <= 85.0:
                        cur.append([round(lon, 2), round(lat, 2)])
                    else:
                        if len(cur) > 1:
                            polys.append(cur)
                        cur = []
                if len(cur) > 1:
                    polys.append(cur)
        out[kind] = polys
        print(f"  {kind}: {len(polys)} polylines")
    path = DATA_DIR / "basemap_world.json.gz"
    path.write_bytes(gzip.compress(json.dumps(out, separators=(",", ":")).encode()))
    print(f"wrote {path} ({path.stat().st_size:,} bytes)")

    print("capturing OpenSky /states/all ...")
    payload = json.loads(_get("https://opensky-network.org/api/states/all"))
    cols: dict[str, list] = {
        k: [] for k in ("hex", "flight", "type", "lat", "lon", "alt", "gs", "track")
    }
    for s in payload.get("states") or []:
        lon, lat = s[5], s[6]
        if lon is None or lat is None:
            continue
        on_ground, alt_m = bool(s[8]), s[7]
        cols["hex"].append(s[0] or "")
        cols["flight"].append((s[1] or "").strip())
        cols["type"].append("")
        cols["lat"].append(round(float(lat), 3))
        cols["lon"].append(round(float(lon), 3))
        cols["alt"].append(
            0.0 if on_ground or not isinstance(alt_m, (int, float)) else round(alt_m * 3.28084)
        )
        cols["gs"].append(round(float(s[9] or 0.0) * 1.94384, 1))
        cols["track"].append(round(float(s[10] or 0.0), 1))
    out = {"source": "opensky /states/all", "time": payload.get("time"), "frames": [cols]}
    path = DATA_DIR / "replay_world.json.gz"
    path.write_bytes(gzip.compress(json.dumps(out, separators=(",", ":")).encode()))
    print(f"wrote {path} ({len(cols['hex'])} aircraft, {path.stat().st_size:,} bytes)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--world", action="store_true", help="rebuild the world-mode assets")
    ap.add_argument("--center", default="50.03,8.57", help="LAT,LON of the query circle")
    ap.add_argument("--radius", type=int, default=250, help="query radius in nm (max 250)")
    ap.add_argument("--frames", type=int, default=10, help="replay frames to capture")
    ap.add_argument("--interval", type=float, default=6.0, help="seconds between frames")
    args = ap.parse_args()
    if args.world:
        build_world()
        return
    lat, lon = (float(v) for v in args.center.split(","))
    build_basemap((lat, lon))
    build_replay((lat, lon), args.radius, args.frames, args.interval)


if __name__ == "__main__":
    main()
