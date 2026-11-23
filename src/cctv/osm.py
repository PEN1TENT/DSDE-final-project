"""Step 6: road and neighbourhood context for every camera from OpenStreetMap (Overpass API).

For each camera this finds the nearest mapped road (class, lanes, one-way, speed limit, bridge)
and counts places that generate or control traffic within RADIUS metres: schools/universities,
hospitals, malls/markets, rail (BTS/MRT/SRT) stations, bus stops, and traffic signals (within
both 100 m and 500 m).

Overpass queries cover all 100 cameras (unions of `around:` filters). The raw JSON
responses are cached in data/raw/external/ so re-runs work offline; pass --refresh to
fetch again. The public servers are often busy, so each query retries with backoff and
falls back to a mirror.

Writes data/interim/osm_context.parquet: one row per camera.

    uv run python -m cctv.osm
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
ROAD_RADIUS = 80  # metres: cameras sit on footbridges/poles right above the road
SIGNAL_RADIUS = 100  # metres: traffic signals at the camera's immediate intersection
RADIUS = 500  # metres for points of interest
ROAD_CLASSES = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service"]
ROAD_RANK = {name: rank for rank, name in enumerate(ROAD_CLASSES)}
POI = {
    "school": '["amenity"~"^(school|university|college|kindergarten)$"]',
    "hospital": '["amenity"~"^(hospital|clinic)$"]',
    "mall_market": '["shop"="mall"]',
    "market": '["amenity"="marketplace"]',
    "rail_station": '["railway"="station"]',
}
TRAFFIC_POI = {
    "traffic_signals": '["highway"="traffic_signals"]',
    "bus_stop": '["highway"="bus_stop"]',
}


def overpass(query: str, cache: Path, refresh: bool) -> dict:
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())
    body = urllib.parse.urlencode({"data": query}).encode()
    wait, last = 5, None
    for attempt in range(8):
        url = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": "cctv-course-project"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.load(resp)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data))
            return data
        except Exception as exc:  # busy server (429/502/504), timeout or HTML error page
            last = exc
            print(f"  {url.split('/')[2]} failed ({exc}); retrying in {wait}s")
            time.sleep(wait)
            wait = min(wait * 2, 60)
    raise RuntimeError(f"Overpass failed after retries: {last}")


def road_query(cams: pd.DataFrame) -> str:
    pattern = "^(" + "|".join(ROAD_CLASSES) + ")(_link)?$"
    parts = [f'way(around:{ROAD_RADIUS},{r.latitude},{r.longitude})["highway"~"{pattern}"];' for r in cams.itertuples()]
    return "[out:json][timeout:180];(" + "".join(parts) + ");out tags geom;"


def poi_query(cams: pd.DataFrame) -> str:
    parts = [f"nwr(around:{RADIUS},{r.latitude},{r.longitude}){f};" for r in cams.itertuples() for f in POI.values()]
    return "[out:json][timeout:180];(" + "".join(parts) + ");out tags center;"


def traffic_query(cams: pd.DataFrame) -> str:
    parts = [f'node(around:{RADIUS},{r.latitude},{r.longitude})["highway"~"^(traffic_signals|bus_stop)$"];'
             for r in cams.itertuples()]
    return "[out:json][timeout:180];(" + "".join(parts) + ");out tags center;"


def to_xy(lat, lon, lat0: float) -> tuple[np.ndarray, np.ndarray]:
    """Local equirectangular metres; accurate to <0.1% across Bangkok."""
    k = 111_320.0
    return np.asarray(lon) * k * np.cos(np.radians(lat0)), np.asarray(lat) * k


def segment_distance(px: float, py: float, xs: np.ndarray, ys: np.ndarray) -> float:
    if len(xs) == 1:
        return float(np.hypot(xs[0] - px, ys[0] - py))
    ax, ay, bx, by = xs[:-1], ys[:-1], xs[1:], ys[1:]
    dx, dy = bx - ax, by - ay
    t = np.clip(((px - ax) * dx + (py - ay) * dy) / np.maximum(dx * dx + dy * dy, 1e-9), 0, 1)
    return float(np.min(np.hypot(ax + t * dx - px, ay + t * dy - py)))


def poi_category(tags: dict) -> str | None:
    amenity = tags.get("amenity", "")
    highway = tags.get("highway", "")
    if amenity in {"school", "university", "college", "kindergarten"}:
        return "school"
    if amenity in {"hospital", "clinic"}:
        return "hospital"
    if tags.get("shop") == "mall" or amenity == "marketplace":
        return "mall_market"
    if tags.get("railway") == "station":
        return "rail_station"
    if highway == "traffic_signals":
        return "traffic_signals"
    if highway == "bus_stop":
        return "bus_stop"
    return None


def number(value: str | None) -> float:
    try:
        return float(str(value).split(";")[0].split()[0])
    except (TypeError, ValueError, IndexError):
        return np.nan


def build(cams: pd.DataFrame, roads: dict, pois: dict, traffic: dict | None = None) -> pd.DataFrame:
    lat0 = float(cams["latitude"].mean())
    ways = []
    for el in roads.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el:
            continue
        xs, ys = to_xy([g["lat"] for g in el["geometry"]], [g["lon"] for g in el["geometry"]], lat0)
        ways.append((el["tags"], xs, ys))
    points = []
    all_poi_elements = list(pois.get("elements", [])) + list((traffic or {}).get("elements", []))
    for el in all_poi_elements:
        loc = el.get("center") or ({"lat": el["lat"], "lon": el["lon"]} if "lat" in el else None)
        cat = poi_category(el.get("tags", {}))
        if loc and cat:
            points.append((el["type"], el["id"], cat, loc["lat"], loc["lon"]))
    poi = pd.DataFrame(points, columns=["type", "id", "cat", "lat", "lon"]).drop_duplicates(["type", "id"])
    poi["x"], poi["y"] = to_xy(poi["lat"], poi["lon"], lat0)

    rows = []
    for cam in cams.itertuples():
        px, py = (float(v) for v in to_xy(cam.latitude, cam.longitude, lat0))
        row = {"camera_id": cam.camera_id}
        best = min(((segment_distance(px, py, xs, ys), tags) for tags, xs, ys in ways), default=None, key=lambda t: t[0])
        # Prefer the biggest road among those within 25 m of the nearest one: a camera over a
        # main road often also touches a service lane or footpath link.
        if best is not None:
            near = [(d, t) for t, xs, ys in ways if (d := segment_distance(px, py, xs, ys)) <= best[0] + 25]
            dist, tags = min(near, key=lambda dt: (ROAD_RANK.get(dt[1]["highway"].removesuffix("_link"), 99), dt[0]))
            road_class = tags["highway"].removesuffix("_link")
            row.update({
                "road_name": tags.get("name:en") or tags.get("name"),
                "road_class": road_class,
                "road_rank": ROAD_RANK.get(road_class, 99),
                "lanes": number(tags.get("lanes")),
                "oneway": tags.get("oneway") == "yes",
                "maxspeed_kmh": number(tags.get("maxspeed")),
                "is_bridge": bool(tags.get("bridge") and tags.get("bridge") != "no"),
                "road_distance_m": round(dist, 1),
            })
        d = np.hypot(poi["x"] - px, poi["y"] - py)
        for cat in ["school", "hospital", "mall_market", "rail_station", "traffic_signals", "bus_stop"]:
            row[f"n_{cat}_{RADIUS}m"] = int(((poi["cat"] == cat) & (d <= RADIUS)).sum())
        row[f"n_traffic_signals_{SIGNAL_RADIUS}m"] = int(((poi["cat"] == "traffic_signals") & (d <= SIGNAL_RADIUS)).sum())
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cameras", type=Path, default=Path("data/raw/cctv_info.csv"))
    parser.add_argument("--cache", type=Path, default=Path("data/raw/external"))
    parser.add_argument("--out", type=Path, default=Path("data/interim/osm_context.parquet"))
    parser.add_argument("--refresh", action="store_true", help="ignore cached responses")
    args = parser.parse_args()

    cams = pd.read_csv(args.cameras, usecols=["camera_id", "latitude", "longitude"])
    print(f"{len(cams)} cameras")
    roads = overpass(road_query(cams), args.cache / "osm_roads.json", args.refresh)
    print(f"  roads: {len(roads.get('elements', []))} ways")
    pois = overpass(poi_query(cams), args.cache / "osm_pois.json", args.refresh)
    print(f"  points of interest: {len(pois.get('elements', []))} elements")
    try:
        traffic = overpass(traffic_query(cams), args.cache / "osm_traffic.json", args.refresh)
        print(f"  traffic nodes (signals / bus stops): {len(traffic.get('elements', []))} elements")
    except Exception as exc:
        print(f"  (traffic nodes skipped: {exc})")
        traffic = None

    out = build(cams, roads, pois, traffic)
    out.to_parquet(args.out, index=False)
    print(f"wrote {args.out}: {len(out)} cameras, {out['road_class'].notna().sum()} matched to a road")
    print(out["road_class"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
