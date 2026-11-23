"""Pure-stdlib external data enrichment for the 100 Bangkok CCTV cameras.

Fetches and caches up to 4 lightweight external datasets into ``data/raw/external/``
with independent fault tolerance and provenance tracking in ``enrichment_manifest.json``:
  1. Open-Meteo historical hourly rain & weather (25-31 Aug 2026) -> ``open_meteo_aug2026.json``
  2. Open-Meteo DEM elevation for all 100 cameras -> ``elevation_100cams.json``
  3. Overpass API traffic signals, bus stops & waterways -> ``osm_extended.json``
  4. Traffy Fondue Bangkok citizen complaints (compact GeoJSON extract) -> ``traffy_bangkok.json``

Usage:
    python -m cctv.external_enrich --cameras data/100_cameras/cctv_info.csv --out-dir data/raw/external
"""

from __future__ import annotations

import argparse
import csv
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

USER_AGENT = "dsde-bangkok-cctv-research/1.0"
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
GRID_STEP = 0.05
ELEVATION_BATCH = 50


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_cameras(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = []
        for r in csv.DictReader(f):
            rows.append(
                {
                    "camera_id": int(r["camera_id"]),
                    "latitude": float(r["latitude"]),
                    "longitude": float(r["longitude"]),
                }
            )
    return rows


def _http_get_json(url: str, timeout: int = 45) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post_json(url: str, form_data: dict[str, str], timeout: int = 60) -> Any:
    body = urllib.parse.urlencode(form_data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _snap_grid(lat: float, lon: float) -> tuple[float, float]:
    return round(round(lat / GRID_STEP) * GRID_STEP, 4), round(round(lon / GRID_STEP) * GRID_STEP, 4)


def fetch_open_meteo_rain(cams: list[dict[str, Any]], out_path: Path, refresh: bool) -> dict[str, Any]:
    """Fetch 25-31 Aug 2026 hourly precipitation/weather on 0.05-degree grid."""
    if out_path.exists() and not refresh:
        data = json.loads(out_path.read_text(encoding="utf-8"))
        return {
            "status": "cached",
            "path": str(out_path),
            "records": len(data.get("grid_points", [])),
            "updated_at": _now_iso(),
            "error": None,
        }
    try:
        points = sorted({_snap_grid(c["latitude"], c["longitude"]) for c in cams})
        lats = ",".join(f"{p[0]:.4f}" for p in points)
        lons = ",".join(f"{p[1]:.4f}" for p in points)
        query = urllib.parse.urlencode(
            {
                "latitude": lats,
                "longitude": lons,
                "hourly": "precipitation,rain,weather_code,temperature_2m",
                "start_date": "2026-08-25",
                "end_date": "2026-08-31",
                "timezone": "Asia/Bangkok",
            }
        )
        url = f"https://archive-api.open-meteo.com/v1/archive?{query}"
        raw = _http_get_json(url, timeout=45)
        items = raw if isinstance(raw, list) else [raw]
        grid_points = []
        for (glat, glon), item in zip(points, items):
            grid_points.append(
                {
                    "glat": glat,
                    "glon": glon,
                    "latitude": item.get("latitude", glat),
                    "longitude": item.get("longitude", glon),
                    "hourly": item.get("hourly", {}),
                }
            )
        payload = {
            "source": "https://archive-api.open-meteo.com/v1/archive",
            "fetched_at": _now_iso(),
            "grid_step": GRID_STEP,
            "start_date": "2026-08-25",
            "end_date": "2026-08-31",
            "timezone": "Asia/Bangkok",
            "grid_points": grid_points,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "status": "fetched_live",
            "path": str(out_path),
            "records": len(grid_points),
            "updated_at": _now_iso(),
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "path": str(out_path),
            "records": 0,
            "updated_at": _now_iso(),
            "error": f"{type(exc).__name__}: {exc}",
        }


def fetch_elevation(cams: list[dict[str, Any]], out_path: Path, refresh: bool) -> dict[str, Any]:
    """Fetch ground elevation (DEM) in metres for all 100 cameras in batches of 50."""
    if out_path.exists() and not refresh:
        data = json.loads(out_path.read_text(encoding="utf-8"))
        return {
            "status": "cached",
            "path": str(out_path),
            "records": len(data.get("elevations", {})),
            "updated_at": _now_iso(),
            "error": None,
        }
    try:
        elevations: dict[str, float] = {}
        for i in range(0, len(cams), ELEVATION_BATCH):
            batch = cams[i : i + ELEVATION_BATCH]
            query = urllib.parse.urlencode(
                {
                    "latitude": ",".join(f"{c['latitude']:.5f}" for c in batch),
                    "longitude": ",".join(f"{c['longitude']:.5f}" for c in batch),
                }
            )
            url = f"https://api.open-meteo.com/v1/elevation?{query}"
            raw = _http_get_json(url, timeout=30)
            vals = raw.get("elevation", [])
            if len(vals) != len(batch):
                raise ValueError(f"Expected {len(batch)} elevation values, got {len(vals)}")
            for cam, val in zip(batch, vals):
                elevations[str(cam["camera_id"])] = float(val)
        payload = {
            "source": "https://api.open-meteo.com/v1/elevation",
            "fetched_at": _now_iso(),
            "elevations": elevations,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "status": "fetched_live",
            "path": str(out_path),
            "records": len(elevations),
            "updated_at": _now_iso(),
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "path": str(out_path),
            "records": 0,
            "updated_at": _now_iso(),
            "error": f"{type(exc).__name__}: {exc}",
        }


def fetch_osm_extended(cams: list[dict[str, Any]], out_path: Path, refresh: bool) -> dict[str, Any]:
    """Fetch nearby traffic signals (100m), bus stops (200m), and waterways (500m) via Overpass."""
    if out_path.exists() and not refresh:
        data = json.loads(out_path.read_text(encoding="utf-8"))
        return {
            "status": "cached",
            "path": str(out_path),
            "records": len(data.get("elements", [])),
            "updated_at": _now_iso(),
            "error": None,
        }
    parts = []
    for c in cams:
        lat, lon = c["latitude"], c["longitude"]
        parts.append(f'node(around:100,{lat},{lon})["highway"="traffic_signals"];')
        parts.append(f'way(around:500,{lat},{lon})["waterway"~"^(canal|river)$"];')
        parts.append(f'node(around:200,{lat},{lon})["highway"="bus_stop"];')
    query = "[out:json][timeout:60];(" + "".join(parts) + ");out tags center;"

    errors: list[str] = []
    for mirror in OVERPASS_MIRRORS:
        try:
            raw = _http_post_json(mirror, {"data": query}, timeout=60)
            els = raw.get("elements", [])
            compact: list[dict[str, Any]] = []
            seen: set[tuple[str, int]] = set()
            for el in els:
                key = (str(el.get("type")), int(el.get("id")))
                if key in seen:
                    continue
                seen.add(key)
                loc = el.get("center") or (
                    {"lat": el["lat"], "lon": el["lon"]} if "lat" in el and "lon" in el else None
                )
                if not loc:
                    continue
                tags = el.get("tags", {})
                keep_tags = {
                    k: tags[k]
                    for k in ("highway", "waterway", "name", "name:en", "crossing")
                    if k in tags
                }
                compact.append(
                    {
                        "type": el.get("type"),
                        "id": el.get("id"),
                        "lat": float(loc["lat"]),
                        "lon": float(loc["lon"]),
                        "tags": keep_tags,
                    }
                )
            payload = {
                "source": mirror,
                "fetched_at": _now_iso(),
                "elements": compact,
            }
            out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return {
                "status": "fetched_live",
                "path": str(out_path),
                "records": len(compact),
                "updated_at": _now_iso(),
                "error": None,
            }
        except Exception as exc:
            errors.append(f"{mirror}: {type(exc).__name__}: {exc}")
    return {
        "status": "unavailable",
        "path": str(out_path),
        "records": 0,
        "updated_at": _now_iso(),
        "error": "; ".join(errors),
    }


def _parse_traffy_categories(raw_type: Any) -> list[str]:
    if isinstance(raw_type, list):
        return [str(x).strip() for x in raw_type if str(x).strip()]
    text = str(raw_type or "").strip()
    if not text or text == "None":
        return []
    text = text.strip("{}")
    return [part.strip().strip('"').strip("'") for part in text.split(",") if part.strip()]


def fetch_traffy_bangkok(out_path: Path, refresh: bool) -> dict[str, Any]:
    """Fetch compact Traffy Fondue Bangkok citizen complaints (<=2500 features, <1.5 MB)."""
    if out_path.exists() and not refresh:
        data = json.loads(out_path.read_text(encoding="utf-8"))
        return {
            "status": "cached",
            "path": str(out_path),
            "records": len(data.get("records", [])),
            "updated_at": _now_iso(),
            "error": None,
        }
    url = "https://publicapi.traffy.in.th/teamchadchart-stat-api/geojson/v1?limit=2500"
    try:
        raw = _http_get_json(url, timeout=35)
        features = raw.get("features", [])
        records: list[dict[str, Any]] = []
        for feat in features:
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates") or []
            if len(coords) < 2:
                continue
            try:
                lon, lat = float(coords[0]), float(coords[1])
            except (TypeError, ValueError):
                continue
            if not (13.4 <= lat <= 14.1 and 100.2 <= lon <= 101.1):
                continue
            props = feat.get("properties") or {}
            cats = _parse_traffy_categories(props.get("type"))
            records.append(
                {
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "types": cats,
                    "state": props.get("state") or "",
                    "timestamp": str(props.get("timestamp") or "")[:19],
                    "district": props.get("district") or "",
                    "subdistrict": props.get("subdistrict") or "",
                }
            )
        payload = {
            "source": url,
            "fetched_at": _now_iso(),
            "records": records,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return {
            "status": "fetched_live",
            "path": str(out_path),
            "records": len(records),
            "updated_at": _now_iso(),
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "path": str(out_path),
            "records": 0,
            "updated_at": _now_iso(),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _simplify_ring(ring: list[list[float]], tol: float = 0.00035) -> list[list[float]]:
    """Distance-thinning simplification + 4-decimal rounding keeping closed polygon rings valid."""
    if len(ring) <= 6:
        return [[round(float(p[0]), 4), round(float(p[1]), 4)] for p in ring]
    kept: list[list[float]] = [[round(float(ring[0][0]), 4), round(float(ring[0][1]), 4)]]
    for pt in ring[1:-1]:
        x, y = round(float(pt[0]), 4), round(float(pt[1]), 4)
        if abs(x - kept[-1][0]) + abs(y - kept[-1][1]) >= tol:
            kept.append([x, y])
    last = [round(float(ring[-1][0]), 4), round(float(ring[-1][1]), 4)]
    if kept[-1] != last:
        kept.append(last)
    if kept[0] != kept[-1]:
        kept.append(kept[0])
    if len(kept) < 4:
        return [[round(float(p[0]), 4), round(float(p[1]), 4)] for p in ring]
    return kept


def _ring_centroid_area(ring: list[list[float]]) -> tuple[float, float, float]:
    """Return (area_abs, centroid_lon, centroid_lat) via shoelace formula."""
    if len(ring) < 3:
        return 0.0, 0.0, 0.0
    a2 = 0.0
    cx = 0.0
    cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        cross = x0 * y1 - x1 * y0
        a2 += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a2) < 1e-12:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return 0.0, sum(xs) / len(xs), sum(ys) / len(ys)
    return abs(a2) * 0.5, cx / (3.0 * a2), cy / (3.0 * a2)


def _normalize_bangkok_feature(feat: dict[str, Any]) -> dict[str, Any] | None:
    props = feat.get("properties") or {}
    geom = feat.get("geometry") or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if gtype not in ("Polygon", "MultiPolygon") or not coords:
        return None

    name_th = str(
        props.get("amp_th")
        or props.get("AMP_TH")
        or props.get("dname")
        or props.get("DNAME")
        or props.get("name_th")
        or props.get("NAME_TH")
        or props.get("th_name")
        or ""
    ).strip()
    name_en = str(
        props.get("amp_en")
        or props.get("AMP_EN")
        or props.get("dname_e")
        or props.get("DNAME_E")
        or props.get("name_en")
        or props.get("NAME_EN")
        or props.get("name")
        or props.get("NAME")
        or ""
    ).strip()
    dcode = str(
        props.get("dcode") or props.get("DCODE") or props.get("amp_code") or props.get("AMP_CODE") or ""
    ).strip()

    # If from nationwide districts file, filter strictly to Bangkok (pro_th / prov_namt / dcode 10xx)
    prov = str(
        props.get("pro_th") or props.get("PROV_NAMT") or props.get("pro_en") or props.get("PROV_NAME") or ""
    ).strip()
    if prov and ("กรุงเทพ" not in prov and "bangkok" not in prov.lower()):
        return None
    if not prov and dcode and not dcode.startswith("10"):
        return None

    if name_th.startswith("เขต"):
        name_th = name_th[3:].strip()
    if not name_th and not name_en:
        return None

    polys = [coords] if gtype == "Polygon" else coords
    simp_polys = [[_simplify_ring(ring) for ring in poly] for poly in polys]
    # Largest outer ring defines visual centroid
    best_area, best_lon, best_lat = -1.0, 0.0, 0.0
    for poly in simp_polys:
        area, clon, clat = _ring_centroid_area(poly[0])
        if area > best_area:
            best_area, best_lon, best_lat = area, clon, clat

    out_coords = simp_polys[0] if gtype == "Polygon" else simp_polys
    return {
        "type": "Feature",
        "properties": {
            "dcode": dcode,
            "name_th": name_th or name_en,
            "name_en": name_en or name_th,
            "centroid_lat": round(best_lat, 5),
            "centroid_lon": round(best_lon, 5),
        },
        "geometry": {"type": gtype, "coordinates": out_coords},
    }


def fetch_bangkok_districts(out_path: Path, refresh: bool = False) -> dict[str, Any]:
    """Fetch and simplify all 50 Bangkok district polygons into GeoJSON (<350 KB)."""
    if out_path.exists() and not refresh:
        data = json.loads(out_path.read_text(encoding="utf-8"))
        return {
            "status": "cached",
            "path": str(out_path),
            "records": len(data.get("features", [])),
            "updated_at": _now_iso(),
            "error": None,
        }
    urls = [
        "https://raw.githubusercontent.com/pcrete/gsvloader-demo/master/geojson/Bangkok-districts.geojson",
        "https://raw.githubusercontent.com/chingchai/OpenGISData-Thailand/master/data/districts.geojson",
    ]
    errors: list[str] = []
    for url in urls:
        try:
            raw = _http_get_json(url, timeout=45)
            feats = []
            for feat in raw.get("features", []):
                norm = _normalize_bangkok_feature(feat)
                if norm is not None:
                    feats.append(norm)
            if len(feats) < 45:
                raise ValueError(f"Expected ~50 Bangkok districts from {url}, got {len(feats)}")
            payload = {
                "type": "FeatureCollection",
                "source": url,
                "fetched_at": _now_iso(),
                "features": feats,
            }
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return {
                "status": "fetched_live",
                "path": str(out_path),
                "records": len(feats),
                "updated_at": _now_iso(),
                "error": None,
            }
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    return {
        "status": "unavailable",
        "path": str(out_path),
        "records": 0,
        "updated_at": _now_iso(),
        "error": "; ".join(errors),
    }


def run(cameras_path: Path, out_dir: Path, refresh: bool = False) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cams = _load_cameras(cameras_path)
    manifest: dict[str, Any] = {
        "generated_at": _now_iso(),
        "cameras": len(cams),
        "sources": {},
    }
    manifest["sources"]["open_meteo_aug2026"] = fetch_open_meteo_rain(
        cams, out_dir / "open_meteo_aug2026.json", refresh
    )
    manifest["sources"]["elevation_100cams"] = fetch_elevation(
        cams, out_dir / "elevation_100cams.json", refresh
    )
    manifest["sources"]["osm_extended"] = fetch_osm_extended(
        cams, out_dir / "osm_extended.json", refresh
    )
    manifest["sources"]["traffy_bangkok"] = fetch_traffy_bangkok(
        out_dir / "traffy_bangkok.json", refresh
    )
    manifest["sources"]["bangkok_districts"] = fetch_bangkok_districts(
        out_dir / "bangkok_districts.geojson", refresh
    )
    manifest_path = out_dir / "enrichment_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cameras", type=Path, default=Path("data/100_cameras/cctv_info.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/raw/external"))
    parser.add_argument("--refresh", action="store_true", help="ignore existing cached JSON files")
    args = parser.parse_args()
    manifest = run(args.cameras, args.out_dir, refresh=args.refresh)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
