"""Pure-stdlib Geospatial, Intersection, Landmark & Urban Storytelling Engine.

Reads raw 100-camera metadata, human-labelled golden counts (`sample.csv`, `export.csv`),
OpenStreetMap caches (`osm_roads.json`, `osm_pois.json`), daylight phases, forensic
camera health (`reports/forensics/camera_forensics.csv`), and any available live-enriched
external datasets (`open_meteo_aug2026.json`, `elevation_100cams.json`, `osm_extended.json`,
`traffy_bangkok.json`).

Writes reproducible structured analytical tables & JSON payloads to ``reports/insights/``:
  - camera_spatial_profile.csv
  - intersection_analysis.csv
  - landmark_dynamics.csv
  - spatial_clusters_and_blindspots.json
  - insights_summary.json

Usage:
    python -m cctv.spatial_insights --out-dir reports/insights
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import random
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

SEED = 403
N_BOOT = 2000
N_PERM = 999
SIAM_LAT, SIAM_LON = 13.7465, 100.5347
ROAD_CLASSES = [
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "service",
]
ROAD_RANK = {name: rank for rank, name in enumerate(ROAD_CLASSES)}
MAJOR_HW = {"motorway", "trunk", "primary", "secondary", "tertiary"}
JUNCTION_ORDER = ["mid-block", "3-way / junction", "4-way crossroad", "5+-way mega"]
WEEKEND_DATES = {"2026-08-29", "2026-08-30"}


def _z_scores(values: list[float]) -> list[float]:
    if not values:
        return []
    mu = statistics.mean(values)
    sd = statistics.pstdev(values)
    if sd <= 1e-12:
        return [0.0 for _ in values]
    return [(v - mu) / sd for v in values]


def _bootstrap_ci(
    values: list[float], rng: random.Random, n_boot: int = N_BOOT
) -> tuple[float, float, float]:
    """Return (mean, ci_low_95, ci_high_95) using deterministic percentile bootstrap."""
    if not values:
        return 0.0, 0.0, 0.0
    n = len(values)
    mu = statistics.mean(values)
    if n == 1:
        return mu, mu, mu
    means = sorted(statistics.mean(rng.choices(values, k=n)) for _ in range(n_boot))
    lo = means[int(0.025 * n_boot)]
    hi = means[min(n_boot - 1, int(0.975 * n_boot))]
    return mu, lo, hi


def _bootstrap_diff_ci(
    vals_a: list[float], vals_b: list[float], rng: random.Random, n_boot: int = N_BOOT
) -> tuple[float, float, float]:
    """Return (mean(A)-mean(B), ci_low_95, ci_high_95)."""
    if not vals_a or not vals_b:
        return 0.0, 0.0, 0.0
    na, nb = len(vals_a), len(vals_b)
    diff = statistics.mean(vals_a) - statistics.mean(vals_b)
    draws = sorted(
        statistics.mean(rng.choices(vals_a, k=na)) - statistics.mean(rng.choices(vals_b, k=nb))
        for _ in range(n_boot)
    )
    return diff, draws[int(0.025 * n_boot)], draws[min(n_boot - 1, int(0.975 * n_boot))]


def _perm_test_diff(
    vals_a: list[float], vals_b: list[float], rng: random.Random, n_perm: int = N_PERM
) -> float:
    """Two-sided permutation p-value for difference in means."""
    if not vals_a or not vals_b:
        return 1.0
    obs = abs(statistics.mean(vals_a) - statistics.mean(vals_b))
    na = len(vals_a)
    pool = list(vals_a) + list(vals_b)
    ge = 0
    for _ in range(n_perm):
        rng.shuffle(pool)
        d = abs(statistics.mean(pool[:na]) - statistics.mean(pool[na:]))
        if d >= obs - 1e-12:
            ge += 1
    return (ge + 1) / (n_perm + 1)


def _solve_linear(A: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for small dense systems."""
    m = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(m):
        piv = max(range(col, m), key=lambda r: abs(M[r][col]))
        M[col], M[piv] = M[piv], M[col]
        div = M[col][col]
        if abs(div) < 1e-12:
            div = 1e-12
        M[col] = [v / div for v in M[col]]
        for r in range(m):
            if r != col:
                f = M[r][col]
                M[r] = [M[r][c] - f * M[col][c] for c in range(m + 1)]
    return [M[i][m] for i in range(m)]


def _fit_ols(
    y: list[float], X_cols: list[tuple[str, list[float]]], standardize: bool = True
) -> dict[str, Any]:
    """Fit multivariate OLS with optional z-score standardization and return full diagnostics."""
    n = len(y)
    p = len(X_cols)
    if standardize:
        std_cols = [(name, _z_scores(col)) for name, col in X_cols]
    else:
        std_cols = X_cols
    X = [[1.0] + [std_cols[j][1][i] for j in range(p)] for i in range(n)]
    XtX = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(p + 1)] for a in range(p + 1)]
    Xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(p + 1)]
    beta = _solve_linear(XtX, Xty)
    yhat = [sum(X[i][j] * beta[j] for j in range(p + 1)) for i in range(n)]
    my = statistics.mean(y)
    ss_res = sum((y[i] - yhat[i]) ** 2 for i in range(n))
    ss_tot = sum((y[i] - my) ** 2 for i in range(n))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    dof = max(1, n - p - 1)
    adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / dof
    s2 = ss_res / dof
    inv: list[list[float]] = []
    for j in range(p + 1):
        e = [1.0 if k == j else 0.0 for k in range(p + 1)]
        inv.append(_solve_linear(XtX, e))

    coefs = []
    for j, (name, _) in enumerate(X_cols):
        se = math.sqrt(max(1e-12, s2 * inv[j + 1][j + 1]))
        b_val = beta[j + 1]
        t_val = b_val / se
        p_approx = math.erfc(abs(t_val) / math.sqrt(2.0))
        coefs.append(
            {
                "feature": name,
                "beta": round(b_val, 4),
                "se": round(se, 4),
                "ci_low": round(b_val - 1.96 * se, 4),
                "ci_high": round(b_val + 1.96 * se, 4),
                "t_stat": round(t_val, 3),
                "p_approx": round(p_approx, 5),
                "significant_05": abs(t_val) >= 1.986,
            }
        )
    return {
        "n": n,
        "p": p,
        "intercept": round(beta[0], 4),
        "r2": round(r2, 4),
        "adj_r2": round(adj_r2, 4),
        "rmse": round(math.sqrt(ss_res / n), 4),
        "coefficients": coefs,
    }


def _to_xy_projector(lat0: float) -> Callable[[float, float], tuple[float, float]]:
    k = 111_320.0
    cos_lat = math.cos(math.radians(lat0))

    def project(lat: float, lon: float) -> tuple[float, float]:
        return lon * k * cos_lat, lat * k

    return project


def _seg_dist(px: float, py: float, pts: list[tuple[float, float]]) -> float:
    if len(pts) == 1:
        return math.hypot(pts[0][0] - px, pts[0][1] - py)
    best = 1e18
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dx, dy = bx - ax, by - ay
        d2 = dx * dx + dy * dy
        t = 0.0 if d2 < 1e-9 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / d2))
        d = math.hypot(ax + t * dx - px, ay + t * dy - py)
        if d < best:
            best = d
    return best


def _count_distinct_arms(angles: list[float], tol: float = 32.0) -> int:
    if not angles:
        return 0
    angs = sorted(angles)
    clusters = [[angs[0]]]
    for a in angs[1:]:
        if a - clusters[-1][-1] < tol:
            clusters[-1].append(a)
        else:
            clusters.append([a])
    if len(clusters) > 1 and (360.0 - clusters[-1][-1] + clusters[0][0]) < tol:
        clusters[0] = clusters[-1] + clusters[0]
        clusters.pop()
    return len(clusters)


def _snap_grid(lat: float, lon: float, step: float = 0.05) -> tuple[float, float]:
    return round(round(lat / step) * step, 4), round(round(lon / step) * step, 4)


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _clean_display_name(loc_th: str, loc_en: str) -> str:
    en = (loc_en or "").strip()
    if en and "connect BMAcctv" not in en:
        return en
    th = (loc_th or "").strip()
    return th if th else "Unknown Camera"


def run_analysis(
    cameras_path: Path,
    sample_path: Path,
    export_path: Path,
    osm_roads_path: Path,
    osm_pois_path: Path,
    daylight_path: Path,
    forensics_cam_path: Path,
    corpus_summary_path: Path,
    external_dir: Path,
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    # 1. Load 100 cameras & forensic health
    with cameras_path.open(encoding="utf-8", newline="") as f:
        cams = {int(r["camera_id"]): r for r in csv.DictReader(f)}
    with forensics_cam_path.open(encoding="utf-8", newline="") as f:
        cam_forensics = {int(r["camera_id"]): r for r in csv.DictReader(f)}
    corpus_summary = json.loads(corpus_summary_path.read_text(encoding="utf-8"))
    daylight = json.loads(daylight_path.read_text(encoding="utf-8"))

    # Optional enriched datasets
    manifest = _load_optional_json(external_dir / "enrichment_manifest.json") or {}
    open_meteo = _load_optional_json(external_dir / "open_meteo_aug2026.json")
    elevation_data = _load_optional_json(external_dir / "elevation_100cams.json")
    osm_ext = _load_optional_json(external_dir / "osm_extended.json")
    traffy_data = _load_optional_json(external_dir / "traffy_bangkok.json")

    rain_grid: dict[tuple[float, float], dict[str, float]] = {}
    if open_meteo and open_meteo.get("grid_points"):
        for gp in open_meteo["grid_points"]:
            key = (round(float(gp["glat"]), 4), round(float(gp["glon"]), 4))
            hourly = gp.get("hourly", {})
            rain_grid[key] = {
                t: float(p)
                for t, p in zip(hourly.get("time", []), hourly.get("precipitation", []))
                if p is not None
            }

    elevations: dict[int, float] = {}
    if elevation_data and elevation_data.get("elevations"):
        elevations = {int(k): float(v) for k, v in elevation_data["elevations"].items()}

    # 2. Golden label processing (strict separation of stratified vs day/model_zero)
    with sample_path.open(encoding="utf-8", newline="") as f:
        sample_rows = list(csv.DictReader(f))
    sample_by_path = {r["path"]: r for r in sample_rows}

    export_by_path: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    with export_path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            export_by_path[r["path"]].append(r)

    cam_busyness: dict[int, str] = {}
    for r in sample_rows:
        if r["stratum"] != "day/model_zero":
            cam_busyness[int(r["camera_id"])] = r["stratum"].split("/")[1]

    strat_frames: list[dict[str, Any]] = []
    model_zero_frames: list[dict[str, Any]] = []
    unusable_count = 0
    double_diffs: list[float] = []

    for path, s in sample_by_path.items():
        rows = export_by_path.get(path, [])
        usable = [r for r in rows if int(r["unusable"]) == 0]
        if not usable:
            unusable_count += 1
            continue
        if len(usable) == 2:
            t1 = sum(float(usable[0][k]) for k in ("car", "motorcycle", "bus", "truck", "bicycle"))
            t2 = sum(float(usable[1][k]) for k in ("car", "motorcycle", "bus", "truck", "bicycle"))
            double_diffs.append(abs(t1 - t2))

        cid = int(s["camera_id"])
        avg = {
            k: sum(float(r[k]) for r in usable) / len(usable)
            for k in ("car", "motorcycle", "bus", "truck", "bicycle")
        }
        avg["total"] = sum(avg.values())
        avg["four_wheel"] = avg["car"] + avg["truck"]
        avg["camera_id"] = cid
        avg["path"] = path
        avg["timestamp"] = s["timestamp"]
        avg["stratum"] = s["stratum"]
        avg["band"] = s["stratum"].split("/")[0] if s["stratum"] != "day/model_zero" else "model_zero"
        dt_obj = datetime.strptime(s["timestamp"], "%Y-%m-%d %H:%M:%S")
        dt_d = dt_obj.strftime("%Y-%m-%d")
        avg["date"] = dt_d
        avg["hour"] = dt_obj.hour
        avg["daytype"] = "weekend" if dt_d in WEEKEND_DATES else "weekday"

        # Daylight phase from daylight.json
        dl = daylight.get(dt_d)
        ts_iso = f"{dt_d}T{dt_obj.strftime('%H:%M:%S')}+07:00"
        if dl:
            if dl["sunrise"] <= ts_iso <= dl["sunset"]:
                avg["light"] = "day"
            elif dl["civil_twilight_begin"] <= ts_iso <= dl["civil_twilight_end"]:
                avg["light"] = "twilight"
            else:
                avg["light"] = "night"
        else:
            avg["light"] = "unknown"

        # Open-Meteo rain matching `cctv.rain` ceil('h') convention
        if rain_grid:
            gkey = _snap_grid(float(cams[cid]["latitude"]), float(cams[cid]["longitude"]))
            ceil_dt = dt_obj.replace(minute=0, second=0) + (
                timedelta(hours=1) if (dt_obj.minute > 0 or dt_obj.second > 0) else timedelta(0)
            )
            prec = rain_grid.get(gkey, {}).get(ceil_dt.strftime("%Y-%m-%dT%H:00"))
            avg["rain_mm"] = prec
            if prec is None:
                avg["rain_level"] = "unknown"
            elif prec <= 0.1:
                avg["rain_level"] = "dry"
            elif prec <= 2.0:
                avg["rain_level"] = "light"
            elif prec <= 5.0:
                avg["rain_level"] = "moderate"
            else:
                avg["rain_level"] = "heavy"
        else:
            avg["rain_mm"] = None
            avg["rain_level"] = "unknown"

        if s["stratum"] == "day/model_zero":
            model_zero_frames.append(avg)
        else:
            strat_frames.append(avg)

    # 3. Road & Intersection Topology + POIs
    lat0 = statistics.mean(float(c["latitude"]) for c in cams.values())
    to_xy = _to_xy_projector(lat0)

    roads_raw = json.loads(osm_roads_path.read_text(encoding="utf-8"))
    ways: list[tuple[int, dict[str, Any], str, list[tuple[float, float]]]] = []
    node_arms: dict[tuple[int, int], list[tuple[float, str]]] = collections.defaultdict(list)
    for el in roads_raw.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el:
            continue
        tags = el.get("tags", {})
        hw = str(tags.get("highway", "")).removesuffix("_link")
        pts = [to_xy(g["lat"], g["lon"]) for g in el["geometry"]]
        ways.append((int(el["id"]), tags, hw, pts))
        if hw in MAJOR_HW:
            nm = str(tags.get("name:en") or tags.get("name") or f"way_{el['id']}")
            for i, (x, y) in enumerate(pts):
                cell = (round(x / 18.0), round(y / 18.0))
                if i > 0:
                    ang = math.degrees(math.atan2(pts[i - 1][1] - y, pts[i - 1][0] - x)) % 360.0
                    node_arms[cell].append((ang, nm))
                if i < len(pts) - 1:
                    ang = math.degrees(math.atan2(pts[i + 1][1] - y, pts[i + 1][0] - x)) % 360.0
                    node_arms[cell].append((ang, nm))

    junction_nodes = []
    for (cx, cy), arms in node_arms.items():
        deg = _count_distinct_arms([a[0] for a in arms])
        if deg >= 3:
            junction_nodes.append((cx * 18.0, cy * 18.0, deg))

    pois_raw = json.loads(osm_pois_path.read_text(encoding="utf-8"))
    poi_list: list[dict[str, Any]] = []
    seen_poi: set[tuple[str, int]] = set()
    for el in pois_raw.get("elements", []):
        key = (str(el.get("type")), int(el.get("id")))
        if key in seen_poi:
            continue
        seen_poi.add(key)
        loc = el.get("center") or ({"lat": el["lat"], "lon": el["lon"]} if "lat" in el else None)
        if not loc:
            continue
        tags = el.get("tags", {})
        am = tags.get("amenity", "")
        cat = None
        if tags.get("shop") == "mall":
            cat = "mall"
        elif am == "marketplace":
            cat = "market"
        elif tags.get("railway") == "station":
            cat = "rail"
        elif am in ("school", "university", "college", "kindergarten"):
            cat = "school"
        elif am in ("hospital", "clinic"):
            cat = "hospital"
        if cat:
            px, py = to_xy(float(loc["lat"]), float(loc["lon"]))
            poi_list.append(
                {
                    "id": key[1],
                    "cat": cat,
                    "name": str(tags.get("name:en") or tags.get("name") or f"Unnamed {cat}"),
                    "name_th": str(tags.get("name") or ""),
                    "lat": float(loc["lat"]),
                    "lon": float(loc["lon"]),
                    "x": px,
                    "y": py,
                }
            )

    # Optional extended OSM (traffic signals, bus stops, canals)
    signals_xy: list[tuple[float, float]] = []
    bus_stops_xy: list[tuple[float, float]] = []
    waterways_xy: list[tuple[float, float, str]] = []
    if osm_ext and osm_ext.get("elements"):
        for el in osm_ext["elements"]:
            tags = el.get("tags", {})
            px, py = to_xy(float(el["lat"]), float(el["lon"]))
            if tags.get("highway") == "traffic_signals":
                signals_xy.append((px, py))
            elif tags.get("highway") == "bus_stop":
                bus_stops_xy.append((px, py))
            elif "waterway" in tags:
                waterways_xy.append((px, py, str(tags.get("name:en") or tags.get("name") or "Canal")))

    # Optional Traffy Fondue
    traffy_pts: list[tuple[float, float, set[str], str]] = []
    if traffy_data and traffy_data.get("records"):
        for rec in traffy_data["records"]:
            px, py = to_xy(float(rec["lat"]), float(rec["lon"]))
            traffy_pts.append((px, py, set(rec.get("types", [])), str(rec.get("district", ""))))

    # Index stratified & model-zero frames per camera
    by_cam_strat: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    for f in strat_frames:
        by_cam_strat[f["camera_id"]].append(f)

    by_cam_mz: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    for f in model_zero_frames:
        by_cam_mz[f["camera_id"]].append(f)

    sx, sy = to_xy(SIAM_LAT, SIAM_LON)
    cam_profiles: dict[int, dict[str, Any]] = {}

    for cid, c in sorted(cams.items()):
        lat, lon = float(c["latitude"]), float(c["longitude"])
        px, py = to_xy(lat, lon)
        near_ways = [
            (d, tags, hw)
            for _, tags, hw, pts in ways
            if (d := _seg_dist(px, py, pts)) <= 80.0
        ]
        road_class, road_name, lanes, oneway, maxspeed, road_dist = (
            "unknown",
            "",
            None,
            False,
            None,
            None,
        )
        has_overpass = False
        distinct_roads: set[str] = set()
        if near_ways:
            min_d = min(w[0] for w in near_ways)
            cand = [(d, t, hw) for d, t, hw in near_ways if d <= min_d + 25.0]
            dist, best_t, best_hw = min(
                cand, key=lambda dt: (ROAD_RANK.get(dt[2], 99), dt[0])
            )
            road_class = best_hw or "unknown"
            road_name = str(best_t.get("name:en") or best_t.get("name") or "")
            try:
                lanes = float(str(best_t.get("lanes", "")).split(";")[0].split()[0])
            except (TypeError, ValueError, IndexError):
                lanes = None
            try:
                maxspeed = float(str(best_t.get("maxspeed", "")).split(";")[0].split()[0])
            except (TypeError, ValueError, IndexError):
                maxspeed = None
            oneway = best_t.get("oneway") == "yes"
            road_dist = round(dist, 1)
            has_overpass = any(t.get("bridge") == "yes" for d, t, _ in near_ways if d <= 60.0)
            for d, t, hw in near_ways:
                if d <= 65.0 and hw in MAJOR_HW:
                    nm = str(t.get("name:en") or t.get("name") or "")
                    if nm:
                        distinct_roads.add(nm)

        near_j = [j for j in junction_nodes if math.hypot(j[0] - px, j[1] - py) <= 75.0]
        max_deg = max((j[2] for j in near_j), default=2)
        loc_str = f"{c['location']} {c['location_en']}".lower()
        is_named_inter = ("แยก" in c["location"]) or ("intersection" in loc_str) or ("junction" in loc_str)
        if max_deg >= 5:
            jtype = "5+-way mega"
        elif max_deg == 4:
            jtype = "4-way crossroad"
        elif max_deg == 3 or is_named_inter or len(distinct_roads) >= 2:
            jtype = "3-way / junction"
        else:
            jtype = "mid-block"

        # Landmarks & named distances
        pcounts = collections.Counter()
        by_cat_dists: dict[str, list[tuple[float, str]]] = collections.defaultdict(list)
        for p in poi_list:
            d = math.hypot(p["x"] - px, p["y"] - py)
            by_cat_dists[p["cat"]].append((d, p["name"]))
            if d <= 500.0:
                pcounts[p["cat"]] += 1
        for cat in by_cat_dists:
            by_cat_dists[cat].sort(key=lambda t: t[0])

        malls_500 = [nm for d, nm in by_cat_dists.get("mall", []) if d <= 500.0 and nm != "Unnamed mall"]
        # Deduplicate preserving order
        seen_m: set[str] = set()
        top_malls: list[str] = []
        for nm in malls_500:
            if nm not in seen_m:
                seen_m.add(nm)
                top_malls.append(nm)
            if len(top_malls) == 4:
                break

        def _nearest(cat: str) -> tuple[str, float | None]:
            lst = by_cat_dists.get(cat, [])
            if not lst:
                return "", None
            return lst[0][1], round(lst[0][0], 1)

        n_mall_nm, n_mall_m = _nearest("mall")
        n_rail_nm, n_rail_m = _nearest("rail")
        n_hosp_nm, n_hosp_m = _nearest("hospital")
        n_sch_nm, n_sch_m = _nearest("school")
        n_mkt_nm, n_mkt_m = _nearest("market")

        is_old_city = (lon < 100.525) and (13.735 <= lat <= 13.790)
        zone = "Old City (Rattanakosin-Dusit)" if is_old_city else "Modern CBD / Arterial"

        # Golden human counts
        fl = by_cam_strat[cid]
        by_band: dict[str, list[float]] = collections.defaultdict(list)
        for f in fl:
            by_band[f["band"]].append(f["total"])
        band_w_mean = statistics.mean(statistics.mean(v) for v in by_band.values()) if by_band else 0.0
        mean_total = statistics.mean(f["total"] for f in fl) if fl else 0.0
        mean_car = statistics.mean(f["car"] for f in fl) if fl else 0.0
        mean_moto = statistics.mean(f["motorcycle"] for f in fl) if fl else 0.0
        mean_bus = statistics.mean(f["bus"] for f in fl) if fl else 0.0
        mean_truck = statistics.mean(f["truck"] for f in fl) if fl else 0.0
        tot_sum = sum(f["total"] for f in fl)
        moto_share = 100.0 * sum(f["motorcycle"] for f in fl) / tot_sum if tot_sum > 0 else 0.0
        wd_vals = [f["total"] for f in fl if f["daytype"] == "weekday"]
        we_vals = [f["total"] for f in fl if f["daytype"] == "weekend"]
        wd_mean = statistics.mean(wd_vals) if wd_vals else None
        we_mean = statistics.mean(we_vals) if we_vals else None
        we_ret = (100.0 * we_mean / wd_mean) if (wd_mean and wd_mean > 0 and we_mean is not None) else None

        # Rain accumulation over the 7 active days (07:00-21:00 ending hours)
        total_rain_week = None
        wet_hours_week = None
        if rain_grid:
            gkey = _snap_grid(lat, lon)
            gdict = rain_grid.get(gkey, {})
            active_vals = [v for k, v in gdict.items() if "T07:00" <= k[10:] <= "T21:00"]
            if active_vals:
                total_rain_week = round(sum(active_vals), 1)
                wet_hours_week = sum(1 for v in active_vals if v > 0.1)

        # Forensic health metrics
        cf = cam_forensics[cid]
        total_files = int(cf["total_files"])
        white_pngs = int(cf["white_pngs"])
        bridged_frozen = int(cf["bridged_frozen"])
        strict_frozen = int(cf["strict_frozen"])
        mz_list = by_cam_mz.get(cid, [])
        mz_max_human = max((f["total"] for f in mz_list), default=0.0)
        mz_mean_human = statistics.mean(f["total"] for f in mz_list) if mz_list else 0.0

        # Extended optional features
        is_signalized = any(math.hypot(x - px, y - py) <= 100.0 for x, y in signals_xy) if signals_xy else None
        n_bus_stops_200m = sum(1 for x, y in bus_stops_xy if math.hypot(x - px, y - py) <= 200.0) if bus_stops_xy else None
        nearest_canal_m = None
        nearest_canal_name = ""
        if waterways_xy:
            d_c, nm_c = min((math.hypot(x - px, y - py), nm) for x, y, nm in waterways_xy)
            nearest_canal_m = round(d_c, 1)
            nearest_canal_name = nm_c

        traffy_500 = None
        traffy_flood_500 = None
        if traffy_pts:
            in500 = [t for x, y, t, _ in traffy_pts if math.hypot(x - px, y - py) <= 500.0]
            traffy_500 = len(in500)
            traffy_flood_500 = sum(1 for t in in500 if any("น้ำท่วม" in x for x in t))

        cam_profiles[cid] = {
            "camera_id": cid,
            "name": _clean_display_name(c["location"], c["location_en"]),
            "location_th": c["location"],
            "location_en": c["location_en"],
            "location_detail_en": c["location_detail_en"],
            "latitude": lat,
            "longitude": lon,
            "x": px,
            "y": py,
            "ip_address": c["ip_address"],
            "subnet_16": cf["subnet_16"],
            "zone": zone,
            "is_old_city": int(is_old_city),
            "dist_siam_km": round(math.hypot(px - sx, py - sy) / 1000.0, 2),
            "road_name": road_name,
            "road_class": road_class,
            "road_rank": ROAD_RANK.get(road_class, 9),
            "lanes": lanes,
            "oneway": int(oneway),
            "maxspeed_kmh": maxspeed,
            "road_distance_m": road_dist,
            "has_overpass": int(has_overpass),
            "n_distinct_roads": len(distinct_roads),
            "junction_degree": max_deg,
            "junction_type": jtype,
            "is_intersection": int(jtype != "mid-block"),
            "n_mall_500m": pcounts["mall"],
            "n_market_500m": pcounts["market"],
            "n_rail_500m": pcounts["rail"],
            "n_hospital_500m": pcounts["hospital"],
            "n_school_500m": pcounts["school"],
            "nearest_mall_name": n_mall_nm,
            "nearest_mall_m": n_mall_m,
            "top_malls_500m": " | ".join(top_malls),
            "nearest_rail_name": n_rail_nm,
            "nearest_rail_m": n_rail_m,
            "nearest_hospital_name": n_hosp_nm,
            "nearest_hospital_m": n_hosp_m,
            "nearest_school_name": n_sch_nm,
            "nearest_school_m": n_sch_m,
            "nearest_market_name": n_mkt_nm,
            "nearest_market_m": n_mkt_m,
            "elevation_m": elevations.get(cid),
            "rain_week_mm": total_rain_week,
            "wet_hours_week": wet_hours_week,
            "is_signalized": is_signalized,
            "n_bus_stops_200m": n_bus_stops_200m,
            "nearest_canal_m": nearest_canal_m,
            "nearest_canal_name": nearest_canal_name,
            "traffy_500m": traffy_500,
            "traffy_flood_500m": traffy_flood_500,
            "busyness_tercile": cam_busyness.get(cid, "unknown"),
            "n_strat_frames": len(fl),
            "band_w_mean": round(band_w_mean, 3),
            "mean_total": round(mean_total, 3),
            "mean_car": round(mean_car, 3),
            "mean_motorcycle": round(mean_moto, 3),
            "mean_bus": round(mean_bus, 3),
            "mean_truck": round(mean_truck, 3),
            "motorcycle_share_pct": round(moto_share, 2),
            "weekday_mean": round(wd_mean, 3) if wd_mean is not None else None,
            "weekend_mean": round(we_mean, 3) if we_mean is not None else None,
            "weekend_retention_pct": round(we_ret, 1) if we_ret is not None else None,
            "total_files": total_files,
            "white_pngs": white_pngs,
            "strict_frozen": strict_frozen,
            "bridged_frozen": bridged_frozen,
            "phase_switches": int(cf["phase_switches"]),
            "thu27_am_status": cf["thu27_am_status"],
            "n_model_zero_frames": len(mz_list),
            "model_zero_mean_human": round(mz_mean_human, 2),
            "model_zero_max_human": round(mz_max_human, 1),
        }

    cids = sorted(cam_profiles.keys())
    n_cams = len(cids)

    # 4. Geospatial Statistics: Moran's I, Getis-Ord Gi*, LISA Quadrants
    W = [[0.0] * n_cams for _ in range(n_cams)]
    S0 = 0.0
    for i in range(n_cams):
        ci = cam_profiles[cids[i]]
        for j in range(n_cams):
            if i == j:
                continue
            cj = cam_profiles[cids[j]]
            d = math.hypot(ci["x"] - cj["x"], ci["y"] - cj["y"])
            if 1.0 < d <= 2500.0:
                w = 1.0 / (d / 1000.0)
                W[i][j] = w
                S0 += w

    W_edges = [(i, j, W[i][j]) for i in range(n_cams) for j in range(n_cams) if W[i][j] > 0.0]

    def _moran(vec: list[float], perms: int = N_PERM) -> tuple[float, float]:
        mu = statistics.mean(vec)
        dev = [v - mu for v in vec]
        den = sum(d * d for d in dev)
        if den <= 1e-12 or S0 <= 1e-12:
            return 0.0, 1.0
        scale = (n_cams / S0) / den
        obs = scale * sum(w * dev[i] * dev[j] for i, j, w in W_edges)
        ge = 0
        for _ in range(perms):
            pv = dev[:]
            rng.shuffle(pv)
            p_i = scale * sum(w * pv[i] * pv[j] for i, j, w in W_edges)
            if p_i >= obs - 1e-12:
                ge += 1
        return round(obs, 4), round((ge + 1) / (perms + 1), 4)

    moran_results: dict[str, dict[str, float]] = {}
    moran_targets = [
        ("traffic_band_w", [cam_profiles[c]["band_w_mean"] for c in cids]),
        ("motorcycle_share", [cam_profiles[c]["motorcycle_share_pct"] for c in cids]),
        ("n_mall_500m", [float(cam_profiles[c]["n_mall_500m"]) for c in cids]),
        ("n_school_500m", [float(cam_profiles[c]["n_school_500m"]) for c in cids]),
        ("bus_mean", [cam_profiles[c]["mean_bus"] for c in cids]),
    ]
    if len(elevations) == n_cams:
        moran_targets.append(("elevation_m", [float(cam_profiles[c]["elevation_m"]) for c in cids]))
    for name, vec in moran_targets:
        val_i, p_val = _moran(vec)
        moran_results[name] = {"morans_i": val_i, "p_value": p_val}

    # Getis-Ord Gi* and LISA (Local Moran's I) on traffic
    t_vals = [cam_profiles[c]["band_w_mean"] for c in cids]
    t_mu = statistics.mean(t_vals)
    t_sd = statistics.pstdev(t_vals) or 1.0
    t_z = [(v - t_mu) / t_sd for v in t_vals]

    for i, cid in enumerate(cids):
        wi = [W[i][j] if i != j else 1.0 for j in range(n_cams)]
        sw = sum(wi)
        sw2 = sum(w * w for w in wi)
        num_g = sum(wi[j] * t_vals[j] for j in range(n_cams)) - t_mu * sw
        den_g = t_sd * math.sqrt(max(1e-12, (n_cams * sw2 - sw * sw) / (n_cams - 1)))
        gi_z = num_g / den_g

        # Row-standardized spatial lag for LISA
        row_sum = sum(W[i])
        lag_z = (sum(W[i][j] * t_z[j] for j in range(n_cams)) / row_sum) if row_sum > 0 else 0.0
        local_i = t_z[i] * lag_z
        if t_z[i] >= 0 and lag_z >= 0:
            lisa_q = "HH"
        elif t_z[i] >= 0 and lag_z < 0:
            lisa_q = "HL"
        elif t_z[i] < 0 and lag_z >= 0:
            lisa_q = "LH"
        else:
            lisa_q = "LL"

        if gi_z >= 1.96:
            gi_cls = "Hotspot (95%)"
        elif gi_z >= 1.65:
            gi_cls = "Hotspot (90%)"
        elif gi_z <= -1.96:
            gi_cls = "Coldspot (95%)"
        elif gi_z <= -1.65:
            gi_cls = "Coldspot (90%)"
        else:
            gi_cls = "Not Significant"

        cam_profiles[cid]["gi_star_z"] = round(gi_z, 3)
        cam_profiles[cid]["gi_star_class"] = gi_cls
        cam_profiles[cid]["local_moran_i"] = round(local_i, 3)
        cam_profiles[cid]["lisa_quadrant"] = lisa_q

    # 5. DBSCAN Congestion Corridors (eps=2.0 km, minPts=3 on busy tercile)
    busy_cids = [c for c in cids if cam_profiles[c]["busyness_tercile"] == "busy"]
    eps_m, min_pts = 2000.0, 3
    visited: set[int] = set()
    db_labels: dict[int, int] = {}
    cluster_id = 0

    def _region(c: int) -> list[int]:
        cx, cy = cam_profiles[c]["x"], cam_profiles[c]["y"]
        return [o for o in busy_cids if math.hypot(cam_profiles[o]["x"] - cx, cam_profiles[o]["y"] - cy) <= eps_m]

    for c in busy_cids:
        if c in visited:
            continue
        visited.add(c)
        nb = _region(c)
        if len(nb) < min_pts:
            db_labels[c] = -1
        else:
            cluster_id += 1
            db_labels[c] = cluster_id
            q = list(nb)
            while q:
                o = q.pop(0)
                if o not in visited:
                    visited.add(o)
                    nb2 = _region(o)
                    if len(nb2) >= min_pts:
                        q.extend(x for x in nb2 if x not in visited)
                if db_labels.get(o, -1) == -1:
                    db_labels[o] = cluster_id

    for c in cids:
        cam_profiles[c]["dbscan_cluster"] = db_labels.get(c, 0)  # 0 = non-busy tercile, -1 = busy outlier

    corridor_names = {
        "central": "Central Mega-Mall & Victory-Siam CBD",
        "thonburi": "Thonburi River-Crossing & BRT Corridor",
        "old_city": "Historic Old-City Chokepoints",
        "ratchada": "Northern Ratchada–Lat Phrao Gateway",
    }
    clusters_meta = []
    grouped_db: dict[int, list[int]] = collections.defaultdict(list)
    for c, lb in db_labels.items():
        grouped_db[lb].append(c)
    for lb, members in sorted(grouped_db.items()):
        if lb == -1:
            continue
        mlat = statistics.mean(cam_profiles[c]["latitude"] for c in members)
        mlon = statistics.mean(cam_profiles[c]["longitude"] for c in members)
        if mlon < 100.495 and mlat < 13.735:
            cname = corridor_names["thonburi"]
        elif mlon < 100.515 and mlat >= 13.74:
            cname = corridor_names["old_city"]
        elif mlat >= 13.79:
            cname = corridor_names["ratchada"]
        else:
            cname = corridor_names["central"]
        clusters_meta.append(
            {
                "cluster_id": lb,
                "name": cname,
                "camera_count": len(members),
                "camera_ids": members,
                "centroid_lat": round(mlat, 5),
                "centroid_lon": round(mlon, 5),
                "mean_traffic": round(statistics.mean(cam_profiles[c]["band_w_mean"] for c in members), 2),
                "total_malls_500m": sum(cam_profiles[c]["n_mall_500m"] for c in members),
                "total_frozen_frames": sum(cam_profiles[c]["bridged_frozen"] for c in members),
            }
        )

    # 6. Gaussian KDE Grid (36 x 28 across Bangkok) & Outer Blind-Spots
    bw_m = 1600.0
    inv_2bw2 = 1.0 / (2.0 * bw_m * bw_m)
    nx_g, ny_g = 36, 28
    lon_min, lon_max = 100.36, 100.82
    lat_min, lat_max = 13.64, 13.92
    kde_grid = []
    max_cam_kde, max_traf_kde = 0.0, 0.0
    for iy in range(ny_g):
        glat = lat_min + (lat_max - lat_min) * (iy / (ny_g - 1))
        for ix in range(nx_g):
            glon = lon_min + (lon_max - lon_min) * (ix / (nx_g - 1))
            gx, gy = to_xy(glat, glon)
            d_cam, d_traf = 0.0, 0.0
            for cid in cids:
                cp = cam_profiles[cid]
                d2 = (gx - cp["x"]) ** 2 + (gy - cp["y"]) ** 2
                if d2 <= (3.5 * bw_m) ** 2:
                    kval = math.exp(-d2 * inv_2bw2)
                    d_cam += kval
                    d_traf += kval * cp["band_w_mean"]
            max_cam_kde = max(max_cam_kde, d_cam)
            max_traf_kde = max(max_traf_kde, d_traf)
            kde_grid.append({"lat": round(glat, 4), "lon": round(glon, 4), "cam_kde": d_cam, "traf_kde": d_traf})
    for cell in kde_grid:
        cell["cam_kde_norm"] = round(cell["cam_kde"] / max_cam_kde, 4) if max_cam_kde else 0.0
        cell["traf_kde_norm"] = round(cell["traf_kde"] / max_traf_kde, 4) if max_traf_kde else 0.0
        cell["cam_kde"] = round(cell["cam_kde"], 4)
        cell["traf_kde"] = round(cell["traf_kde"], 3)

    lats_all = [cam_profiles[c]["latitude"] for c in cids]
    lons_all = [cam_profiles[c]["longitude"] for c in cids]
    blind_spots = {
        "bbox": {
            "lat_min": round(min(lats_all), 4),
            "lat_max": round(max(lats_all), 4),
            "lon_min": round(min(lons_all), 4),
            "lon_max": round(max(lons_all), 4),
        },
        "outer_counts": {
            "north_gt_13_84": {
                "cameras": sum(1 for x in lats_all if x > 13.84),
                "districts": "Don Mueang, Sai Mai, Bang Khen, Lak Si",
            },
            "south_lt_13_68": {
                "cameras": sum(1 for x in lats_all if x < 13.68),
                "districts": "Bang Khun Thian, Thung Khru, Bang Bon, Rat Burana",
            },
            "east_gt_100_62": {
                "cameras": sum(1 for x in lons_all if x > 100.62),
                "districts": "Min Buri, Lat Krabang, Nong Chok, Khlong Sam Wa, Prawet",
            },
            "west_lt_100_45": {
                "cameras": sum(1 for x in lons_all if x < 100.45),
                "districts": "Bang Khae, Nong Khaem, Thawi Watthana",
            },
        },
    }

    # 7. Intersection Analysis (with Bootstrap CIs) & Compound Friction 2x2
    inter_rows = []
    for jt in JUNCTION_ORDER:
        sub_c = [cam_profiles[c] for c in cids if cam_profiles[c]["junction_type"] == jt]
        sub_f = [f for f in strat_frames if cam_profiles[f["camera_id"]]["junction_type"] == jt]
        mu, lo, hi = _bootstrap_ci([f["total"] for f in sub_f], rng)
        busy_cnt = sum(1 for r in sub_c if r["busyness_tercile"] == "busy")
        frz_cnt = sum(r["bridged_frozen"] for r in sub_c)
        inter_rows.append(
            {
                "group_type": "junction_topology",
                "segment": jt,
                "cameras": len(sub_c),
                "busy_cameras": busy_cnt,
                "busy_pct": round(100.0 * busy_cnt / max(1, len(sub_c)), 1),
                "frames": len(sub_f),
                "mean_total": round(mu, 2),
                "ci_low": round(lo, 2),
                "ci_high": round(hi, 2),
                "mean_car": round(statistics.mean(f["car"] for f in sub_f), 2),
                "mean_motorcycle": round(statistics.mean(f["motorcycle"] for f in sub_f), 2),
                "mean_bus": round(statistics.mean(f["bus"] for f in sub_f), 2),
                "mean_truck": round(statistics.mean(f["truck"] for f in sub_f), 2),
                "frozen_frames": frz_cnt,
            }
        )

    compound_specs = [
        ("Intersection + Mall/Rail", lambda r: r["is_intersection"] == 1 and (r["n_mall_500m"] >= 1 or r["n_rail_500m"] >= 1)),
        ("Intersection, No Mall/Rail", lambda r: r["is_intersection"] == 1 and r["n_mall_500m"] == 0 and r["n_rail_500m"] == 0),
        ("Mid-block + Mall/Rail", lambda r: r["is_intersection"] == 0 and (r["n_mall_500m"] >= 1 or r["n_rail_500m"] >= 1)),
        ("Mid-block, No Mall/Rail", lambda r: r["is_intersection"] == 0 and r["n_mall_500m"] == 0 and r["n_rail_500m"] == 0),
    ]
    for lbl, pred in compound_specs:
        sub_c = [cam_profiles[c] for c in cids if pred(cam_profiles[c])]
        sub_f = [f for f in strat_frames if pred(cam_profiles[f["camera_id"]])]
        mu, lo, hi = _bootstrap_ci([f["total"] for f in sub_f], rng)
        busy_cnt = sum(1 for r in sub_c if r["busyness_tercile"] == "busy")
        frz_cnt = sum(r["bridged_frozen"] for r in sub_c)
        inter_rows.append(
            {
                "group_type": "compound_friction_2x2",
                "segment": lbl,
                "cameras": len(sub_c),
                "busy_cameras": busy_cnt,
                "busy_pct": round(100.0 * busy_cnt / max(1, len(sub_c)), 1),
                "frames": len(sub_f),
                "mean_total": round(mu, 2),
                "ci_low": round(lo, 2),
                "ci_high": round(hi, 2),
                "mean_car": round(statistics.mean(f["car"] for f in sub_f), 2),
                "mean_motorcycle": round(statistics.mean(f["motorcycle"] for f in sub_f), 2),
                "mean_bus": round(statistics.mean(f["bus"] for f in sub_f), 2),
                "mean_truck": round(statistics.mean(f["truck"] for f in sub_f), 2),
                "frozen_frames": frz_cnt,
            }
        )

    # Old City vs Modern CBD (including 4-way crossroad Simpson's paradox test)
    zone_specs = [
        ("Old City (All)", lambda r: r["is_old_city"] == 1),
        ("Modern CBD / Arterial (All)", lambda r: r["is_old_city"] == 0),
        ("Old City (4-way Crossroads)", lambda r: r["is_old_city"] == 1 and r["junction_type"] == "4-way crossroad"),
        ("Modern CBD (4-way Crossroads)", lambda r: r["is_old_city"] == 0 and r["junction_type"] == "4-way crossroad"),
    ]
    for lbl, pred in zone_specs:
        sub_c = [cam_profiles[c] for c in cids if pred(cam_profiles[c])]
        sub_f = [f for f in strat_frames if pred(cam_profiles[f["camera_id"]])]
        mu, lo, hi = _bootstrap_ci([f["total"] for f in sub_f], rng)
        busy_cnt = sum(1 for r in sub_c if r["busyness_tercile"] == "busy")
        inter_rows.append(
            {
                "group_type": "two_bangkoks_zone",
                "segment": lbl,
                "cameras": len(sub_c),
                "busy_cameras": busy_cnt,
                "busy_pct": round(100.0 * busy_cnt / max(1, len(sub_c)), 1),
                "frames": len(sub_f),
                "mean_total": round(mu, 2),
                "ci_low": round(lo, 2),
                "ci_high": round(hi, 2),
                "mean_car": round(statistics.mean(f["car"] for f in sub_f), 2),
                "mean_motorcycle": round(statistics.mean(f["motorcycle"] for f in sub_f), 2),
                "mean_bus": round(statistics.mean(f["bus"] for f in sub_f), 2),
                "mean_truck": round(statistics.mean(f["truck"] for f in sub_f), 2),
                "frozen_frames": sum(r["bridged_frozen"] for r in sub_c),
            }
        )

    with (out_dir / "intersection_analysis.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(inter_rows[0].keys()))
        writer.writeheader()
        writer.writerows(inter_rows)

    # 8. Landmark Weekday/Weekend Dynamics & Distance Decay
    landmark_rows = []
    landmark_specs = [
        ("Mega-Mall Hub (>=3 malls)", lambda r: r["n_mall_500m"] >= 3),
        ("Near Mall (1-2 malls)", lambda r: 1 <= r["n_mall_500m"] <= 2),
        ("No Mall (0 malls)", lambda r: r["n_mall_500m"] == 0),
        ("Near BTS/MRT (>=1 rail)", lambda r: r["n_rail_500m"] >= 1),
        ("No Rail within 500m", lambda r: r["n_rail_500m"] == 0),
        ("Near Hospital (>=1 hosp)", lambda r: r["n_hospital_500m"] >= 1),
        ("School-Heavy (>=3 schools)", lambda r: r["n_school_500m"] >= 3),
        ("4+ Way Intersection", lambda r: r["junction_degree"] >= 4),
    ]
    for lbl, pred in landmark_specs:
        sub_c = [cam_profiles[c] for c in cids if pred(cam_profiles[c])]
        wd_f = [f for f in strat_frames if f["daytype"] == "weekday" and pred(cam_profiles[f["camera_id"]])]
        we_f = [f for f in strat_frames if f["daytype"] == "weekend" and pred(cam_profiles[f["camera_id"]])]
        all_f = wd_f + we_f
        wd_mu, wd_lo, wd_hi = _bootstrap_ci([f["total"] for f in wd_f], rng)
        we_mu, we_lo, we_hi = _bootstrap_ci([f["total"] for f in we_f], rng)
        diff, d_lo, d_hi = _bootstrap_diff_ci([f["total"] for f in we_f], [f["total"] for f in wd_f], rng)
        tot_s = sum(f["total"] for f in all_f)
        landmark_rows.append(
            {
                "category": "weekday_weekend",
                "segment": lbl,
                "cameras": len(sub_c),
                "all_frames": len(all_f),
                "all_mean": round(statistics.mean(f["total"] for f in all_f), 2),
                "moto_share_pct": round(100.0 * sum(f["motorcycle"] for f in all_f) / tot_s, 1) if tot_s else 0.0,
                "bus_mean": round(statistics.mean(f["bus"] for f in all_f), 2),
                "weekday_frames": len(wd_f),
                "weekday_mean": round(wd_mu, 2),
                "weekday_ci_low": round(wd_lo, 2),
                "weekday_ci_high": round(wd_hi, 2),
                "weekend_frames": len(we_f),
                "weekend_mean": round(we_mu, 2),
                "weekend_ci_low": round(we_lo, 2),
                "weekend_ci_high": round(we_hi, 2),
                "we_minus_wd": round(diff, 2),
                "we_minus_wd_pct": round(100.0 * diff / wd_mu, 1) if wd_mu else 0.0,
                "diff_ci_low": round(d_lo, 2),
                "diff_ci_high": round(d_hi, 2),
            }
        )

    # Distance-decay bins for Malls & Rail
    decay_bins = [
        ("0-150m", lambda d: d is not None and d <= 150.0),
        ("150-300m", lambda d: d is not None and 150.0 < d <= 300.0),
        ("300-500m", lambda d: d is not None and 300.0 < d <= 500.0),
        (">500m", lambda d: d is None or d > 500.0),
    ]
    for kind, col in [("mall_decay", "nearest_mall_m"), ("rail_decay", "nearest_rail_m")]:
        for bname, bpred in decay_bins:
            sub_c = [cam_profiles[c] for c in cids if bpred(cam_profiles[c][col])]
            sub_f = [f for f in strat_frames if bpred(cam_profiles[f["camera_id"]][col])]
            if not sub_f:
                continue
            mu, lo, hi = _bootstrap_ci([f["total"] for f in sub_f], rng)
            tot_s = sum(f["total"] for f in sub_f)
            landmark_rows.append(
                {
                    "category": kind,
                    "segment": bname,
                    "cameras": len(sub_c),
                    "all_frames": len(sub_f),
                    "all_mean": round(mu, 2),
                    "moto_share_pct": round(100.0 * sum(f["motorcycle"] for f in sub_f) / tot_s, 1) if tot_s else 0.0,
                    "bus_mean": round(statistics.mean(f["bus"] for f in sub_f), 2),
                    "weekday_frames": sum(1 for f in sub_f if f["daytype"] == "weekday"),
                    "weekday_mean": round(mu, 2),
                    "weekday_ci_low": round(lo, 2),
                    "weekday_ci_high": round(hi, 2),
                    "weekend_frames": sum(1 for f in sub_f if f["daytype"] == "weekend"),
                    "weekend_mean": round(mu, 2),
                    "weekend_ci_low": round(lo, 2),
                    "weekend_ci_high": round(hi, 2),
                    "we_minus_wd": 0.0,
                    "we_minus_wd_pct": 0.0,
                    "diff_ci_low": 0.0,
                    "diff_ci_high": 0.0,
                }
            )

    with (out_dir / "landmark_dynamics.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(landmark_rows[0].keys()))
        writer.writeheader()
        writer.writerows(landmark_rows)

    # 9. Modal Shift by Band x Daytype + Human-Verified Rain Modal Shift
    band_daytype_modal = []
    for band in ("morning", "midday", "evening", "night"):
        for dt in ("weekday", "weekend"):
            sub = [f for f in strat_frames if f["band"] == band and f["daytype"] == dt]
            tot_s = sum(f["total"] for f in sub)
            band_daytype_modal.append(
                {
                    "band": band,
                    "daytype": dt,
                    "frames": len(sub),
                    "mean_total": round(statistics.mean(f["total"] for f in sub), 2),
                    "mean_car": round(statistics.mean(f["car"] for f in sub), 2),
                    "mean_motorcycle": round(statistics.mean(f["motorcycle"] for f in sub), 2),
                    "mean_bus": round(statistics.mean(f["bus"] for f in sub), 2),
                    "motorcycle_share_pct": round(100.0 * sum(f["motorcycle"] for f in sub) / tot_s, 1) if tot_s else 0.0,
                }
            )

    rain_modal_summary: dict[str, Any] = {"available": bool(rain_grid), "levels": [], "evening_wet_vs_dry": {}}
    if rain_grid:
        for lvl in ("dry", "light", "moderate", "heavy"):
            sub = [f for f in strat_frames if f["rain_level"] == lvl]
            if not sub:
                continue
            tot_s = sum(f["total"] for f in sub)
            rain_modal_summary["levels"].append(
                {
                    "rain_level": lvl,
                    "frames": len(sub),
                    "mean_total": round(statistics.mean(f["total"] for f in sub), 2),
                    "mean_car": round(statistics.mean(f["car"] for f in sub), 2),
                    "mean_motorcycle": round(statistics.mean(f["motorcycle"] for f in sub), 2),
                    "motorcycle_share_pct": round(100.0 * sum(f["motorcycle"] for f in sub) / tot_s, 1) if tot_s else 0.0,
                }
            )
        ev_dry = [f for f in strat_frames if f["band"] == "evening" and f["rain_level"] == "dry"]
        ev_wet = [f for f in strat_frames if f["band"] == "evening" and f["rain_level"] in ("light", "moderate", "heavy")]
        if ev_dry and ev_wet:
            m_diff, m_lo, m_hi = _bootstrap_diff_ci(
                [f["motorcycle"] for f in ev_wet], [f["motorcycle"] for f in ev_dry], rng
            )
            rain_modal_summary["evening_wet_vs_dry"] = {
                "dry_frames": len(ev_dry),
                "wet_frames": len(ev_wet),
                "dry_car": round(statistics.mean(f["car"] for f in ev_dry), 2),
                "wet_car": round(statistics.mean(f["car"] for f in ev_wet), 2),
                "dry_moto": round(statistics.mean(f["motorcycle"] for f in ev_dry), 2),
                "wet_moto": round(statistics.mean(f["motorcycle"] for f in ev_wet), 2),
                "dry_moto_share_pct": round(100.0 * sum(f["motorcycle"] for f in ev_dry) / sum(f["total"] for f in ev_dry), 1),
                "wet_moto_share_pct": round(100.0 * sum(f["motorcycle"] for f in ev_wet) / sum(f["total"] for f in ev_wet), 1),
                "moto_diff": round(m_diff, 2),
                "moto_diff_ci": [round(m_lo, 2), round(m_hi, 2)],
            }

    # 10. Multivariate OLS (Base vs Spatial-Zone Controlled)
    y_ols = [cam_profiles[c]["band_w_mean"] for c in cids]
    base_cols = [
        ("is_major_road", [1.0 if cam_profiles[c]["road_class"] in ("motorway", "trunk", "primary") else 0.0 for c in cids]),
        ("is_intersection", [float(cam_profiles[c]["is_intersection"]) for c in cids]),
        ("has_overpass", [float(cam_profiles[c]["has_overpass"]) for c in cids]),
        ("log_mall", [math.log1p(cam_profiles[c]["n_mall_500m"]) for c in cids]),
        ("has_rail", [1.0 if cam_profiles[c]["n_rail_500m"] >= 1 else 0.0 for c in cids]),
        ("has_hospital", [1.0 if cam_profiles[c]["n_hospital_500m"] >= 1 else 0.0 for c in cids]),
        ("log_school", [math.log1p(cam_profiles[c]["n_school_500m"]) for c in cids]),
        ("dist_siam_km", [cam_profiles[c]["dist_siam_km"] for c in cids]),
    ]
    ols_base = _fit_ols(y_ols, base_cols, standardize=True)

    spatial_cols = base_cols + [("is_old_city", [float(cam_profiles[c]["is_old_city"]) for c in cids])]
    if len(elevations) == n_cams:
        spatial_cols.append(("elevation_m", [float(cam_profiles[c]["elevation_m"]) for c in cids]))
    ols_spatial = _fit_ols(y_ols, spatial_cols, standardize=True)

    # 11. Camera Health Paradox & Upgrade Priority Score
    health_groups = []
    for lbl, pred in [
        ("Busy tercile", lambda r: r["busyness_tercile"] == "busy"),
        ("Medium tercile", lambda r: r["busyness_tercile"] == "medium"),
        ("Quiet tercile", lambda r: r["busyness_tercile"] == "quiet"),
        ("Intersection", lambda r: r["is_intersection"] == 1),
        ("Mid-block", lambda r: r["is_intersection"] == 0),
        ("Near Mall (>=1)", lambda r: r["n_mall_500m"] >= 1),
        ("No Mall", lambda r: r["n_mall_500m"] == 0),
    ]:
        sub = [cam_profiles[c] for c in cids if pred(cam_profiles[c])]
        frz_cams = sum(1 for r in sub if r["bridged_frozen"] > 0)
        frz_tot = sum(r["bridged_frozen"] for r in sub)
        health_groups.append(
            {
                "segment": lbl,
                "cameras": len(sub),
                "frozen_cameras": frz_cams,
                "frozen_camera_pct": round(100.0 * frz_cams / max(1, len(sub)), 1),
                "total_frozen_frames": frz_tot,
            }
        )

    busy_frz_flags = [1.0 if cam_profiles[c]["bridged_frozen"] > 0 else 0.0 for c in cids if cam_profiles[c]["busyness_tercile"] == "busy"]
    quiet_frz_flags = [1.0 if cam_profiles[c]["bridged_frozen"] > 0 else 0.0 for c in cids if cam_profiles[c]["busyness_tercile"] == "quiet"]
    inter_frz_flags = [1.0 if cam_profiles[c]["bridged_frozen"] > 0 else 0.0 for c in cids if cam_profiles[c]["is_intersection"] == 1]
    mid_frz_flags = [1.0 if cam_profiles[c]["bridged_frozen"] > 0 else 0.0 for c in cids if cam_profiles[c]["is_intersection"] == 0]

    # Transparent weighted Upgrade-First Priority Score
    z_traf = _z_scores([cam_profiles[c]["band_w_mean"] for c in cids])
    z_land = _z_scores(
        [
            float(cam_profiles[c]["n_mall_500m"] + cam_profiles[c]["n_rail_500m"] + cam_profiles[c]["is_intersection"])
            for c in cids
        ]
    )
    z_fail = _z_scores(
        [
            math.log1p(cam_profiles[c]["bridged_frozen"])
            + 0.5 * (cam_profiles[c]["white_pngs"] / max(1, cam_profiles[c]["total_files"]))
            + 0.5 * (cam_profiles[c]["model_zero_max_human"] / 40.0)
            for c in cids
        ]
    )
    scored = []
    for i, cid in enumerate(cids):
        score = 0.40 * z_traf[i] + 0.25 * z_land[i] + 0.35 * z_fail[i]
        cam_profiles[cid]["upgrade_priority_score"] = round(score, 3)
        scored.append((score, cid))
    scored.sort(reverse=True)
    for rank, (_, cid) in enumerate(scored, start=1):
        cam_profiles[cid]["upgrade_rank"] = rank

    # Write camera_spatial_profile.csv (exclude raw x, y internal projection cols or keep cleanly)
    out_cam_rows = []
    for cid in cids:
        row = dict(cam_profiles[cid])
        row.pop("x", None)
        row.pop("y", None)
        out_cam_rows.append(row)

    with (out_dir / "camera_spatial_profile.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out_cam_rows[0].keys()))
        writer.writeheader()
        writer.writerows(out_cam_rows)

    # AI Blind-spots summary
    mz_nonzero = [f for f in model_zero_frames if f["total"] > 0]
    top_mz = sorted(model_zero_frames, key=lambda x: x["total"], reverse=True)[:10]
    top_mz_clean = [
        {
            "camera_id": f["camera_id"],
            "name": cam_profiles[f["camera_id"]]["name"],
            "timestamp": f["timestamp"],
            "human_total": round(f["total"], 1),
            "human_car": round(f["car"], 1),
            "human_motorcycle": round(f["motorcycle"], 1),
            "road_class": cam_profiles[f["camera_id"]]["road_class"],
            "junction_type": cam_profiles[f["camera_id"]]["junction_type"],
        }
        for f in top_mz
    ]

    # Top 10 Upgrade Priority Cameras
    top10_upgrade = [
        {
            "rank": cam_profiles[cid]["upgrade_rank"],
            "camera_id": cid,
            "name": cam_profiles[cid]["name"],
            "zone": cam_profiles[cid]["zone"],
            "road_class": cam_profiles[cid]["road_class"],
            "junction_type": cam_profiles[cid]["junction_type"],
            "band_w_mean": cam_profiles[cid]["band_w_mean"],
            "n_mall_500m": cam_profiles[cid]["n_mall_500m"],
            "n_rail_500m": cam_profiles[cid]["n_rail_500m"],
            "top_malls_500m": cam_profiles[cid]["top_malls_500m"],
            "nearest_rail_name": cam_profiles[cid]["nearest_rail_name"],
            "bridged_frozen": cam_profiles[cid]["bridged_frozen"],
            "white_pngs": cam_profiles[cid]["white_pngs"],
            "model_zero_max_human": cam_profiles[cid]["model_zero_max_human"],
            "upgrade_priority_score": cam_profiles[cid]["upgrade_priority_score"],
            "gi_star_z": cam_profiles[cid]["gi_star_z"],
        }
        for _, cid in scored[:10]
    ]

    # Spatial clusters & blindspots JSON (also export POI coordinates for the HTML dashboard)
    clusters_payload = {
        "bbox": blind_spots["bbox"],
        "outer_blind_spots": blind_spots["outer_counts"],
        "dbscan": {
            "eps_m": eps_m,
            "min_pts": min_pts,
            "busy_cameras": len(busy_cids),
            "noise_busy_cameras": [c for c, lb in db_labels.items() if lb == -1],
            "corridors": clusters_meta,
        },
        "kde_grid": kde_grid,
        "pois": [
            {
                "cat": p["cat"],
                "name": p["name"],
                "lat": round(p["lat"], 6),
                "lon": round(p["lon"], 6),
            }
            for p in poi_list
        ],
    }
    (out_dir / "spatial_clusters_and_blindspots.json").write_text(
        json.dumps(clusters_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Top hotspots & coldspots
    hotspots = sorted(out_cam_rows, key=lambda r: r["gi_star_z"], reverse=True)[:8]
    coldspots = sorted(out_cam_rows, key=lambda r: r["gi_star_z"])[:6]
    busiest = sorted(out_cam_rows, key=lambda r: r["band_w_mean"], reverse=True)[:10]

    hourly_cov_path = corpus_summary_path.parent / "hourly_coverage.csv"
    complete_hour_snapshots = 0
    complete_active_cells = 0
    if hourly_cov_path.exists():
        with hourly_cov_path.open(encoding="utf-8", newline="") as f:
            for hr in csv.DictReader(f):
                if int(hr["hour"]) < 21 and int(hr["valid_live_jpegs"]) >= 3:
                    complete_active_cells += 1
                    complete_hour_snapshots += int(hr["valid_live_jpegs"])

    insights_summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "seed": SEED,
        "corpus": {
            "cameras": n_cams,
            "raw_files": corpus_summary["total_files"],
            "clean_live_jpegs": corpus_summary["non_frozen_live_jpegs"],
            "clean_complete_snapshots": complete_hour_snapshots,
            "complete_active_cells": complete_active_cells,
            "bridged_frozen_total": corpus_summary["bridged_frozen"],
            "white_pngs_total": corpus_summary["white_pngs"],
        },
        "golden_reconciliation": {
            "sampled_paths": len(sample_by_path),
            "usable_total": len(strat_frames) + len(model_zero_frames),
            "stratified_usable": len(strat_frames),
            "model_zero_usable": len(model_zero_frames),
            "unusable_frames": unusable_count,
            "double_counted_usable": len(double_diffs),
            "inter_annotator_mae": round(statistics.mean(double_diffs), 2) if double_diffs else 0.0,
            "tercile_counts": dict(collections.Counter(cam_profiles[c]["busyness_tercile"] for c in cids)),
        },
        "external_sources": manifest.get("sources", {}),
        "moran_i": moran_results,
        "two_bangkoks": {
            row["segment"]: row
            for row in inter_rows
            if row["group_type"] == "two_bangkoks_zone"
        },
        "intersections": [row for row in inter_rows if row["group_type"] == "junction_topology"],
        "compound_friction_2x2": [row for row in inter_rows if row["group_type"] == "compound_friction_2x2"],
        "landmarks": [row for row in landmark_rows if row["category"] == "weekday_weekend"],
        "distance_decay": [row for row in landmark_rows if row["category"] in ("mall_decay", "rail_decay")],
        "modal_by_band_daytype": band_daytype_modal,
        "rain_modal_shift": rain_modal_summary,
        "ols_base": ols_base,
        "ols_spatial_controlled": ols_spatial,
        "ai_blind_spots": {
            "total_usable_model_zero": len(model_zero_frames),
            "nonzero_human_frames": len(mz_nonzero),
            "false_empty_pct": round(100.0 * len(mz_nonzero) / max(1, len(model_zero_frames)), 1),
            "mean_human_total": round(statistics.mean(f["total"] for f in model_zero_frames), 2),
            "max_human_total": round(max(f["total"] for f in model_zero_frames), 1),
            "top_frames": top_mz_clean,
        },
        "camera_health_paradox": {
            "groups": health_groups,
            "busy_vs_quiet_perm_p": round(_perm_test_diff(busy_frz_flags, quiet_frz_flags, rng), 4),
            "inter_vs_mid_perm_p": round(_perm_test_diff(inter_frz_flags, mid_frz_flags, rng), 4),
            "intersection_share_of_frozen_pct": round(
                100.0
                * sum(cam_profiles[c]["bridged_frozen"] for c in cids if cam_profiles[c]["is_intersection"] == 1)
                / max(1, sum(cam_profiles[c]["bridged_frozen"] for c in cids)),
                1,
            ),
        },
        "elevation_summary": {
            "available": len(elevations) == n_cams,
            "min_m": min(elevations.values()) if elevations else None,
            "median_m": statistics.median(elevations.values()) if elevations else None,
            "max_m": max(elevations.values()) if elevations else None,
        },
        "hotspots_top8": [
            {
                "camera_id": r["camera_id"],
                "name": r["name"],
                "gi_star_z": r["gi_star_z"],
                "band_w_mean": r["band_w_mean"],
                "n_mall_500m": r["n_mall_500m"],
                "n_rail_500m": r["n_rail_500m"],
            }
            for r in hotspots
        ],
        "coldspots_top6": [
            {
                "camera_id": r["camera_id"],
                "name": r["name"],
                "gi_star_z": r["gi_star_z"],
                "band_w_mean": r["band_w_mean"],
            }
            for r in coldspots
        ],
        "busiest_top10": [
            {
                "camera_id": r["camera_id"],
                "name": r["name"],
                "band_w_mean": r["band_w_mean"],
                "mean_total": r["mean_total"],
                "junction_type": r["junction_type"],
                "n_mall_500m": r["n_mall_500m"],
                "top_malls_500m": r["top_malls_500m"],
            }
            for r in busiest
        ],
        "top10_upgrade_priority": top10_upgrade,
    }
    (out_dir / "insights_summary.json").write_text(
        json.dumps(insights_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return insights_summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cameras", type=Path, default=Path("data/100_cameras/cctv_info.csv"))
    parser.add_argument("--sample", type=Path, default=Path("data/labels/sample.csv"))
    parser.add_argument("--export", type=Path, default=Path("data/labels/export.csv"))
    parser.add_argument("--osm-roads", type=Path, default=Path("data/raw/external/osm_roads.json"))
    parser.add_argument("--osm-pois", type=Path, default=Path("data/raw/external/osm_pois.json"))
    parser.add_argument("--daylight", type=Path, default=Path("data/raw/external/daylight.json"))
    parser.add_argument(
        "--forensics-cams", type=Path, default=Path("reports/forensics/camera_forensics.csv")
    )
    parser.add_argument(
        "--corpus-summary", type=Path, default=Path("reports/forensics/corpus_summary.json")
    )
    parser.add_argument("--external-dir", type=Path, default=Path("data/raw/external"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/insights"))
    args = parser.parse_args()

    summary = run_analysis(
        cameras_path=args.cameras,
        sample_path=args.sample,
        export_path=args.export,
        osm_roads_path=args.osm_roads,
        osm_pois_path=args.osm_pois,
        daylight_path=args.daylight,
        forensics_cam_path=args.forensics_cams,
        corpus_summary_path=args.corpus_summary,
        external_dir=args.external_dir,
        out_dir=args.out_dir,
    )
    print(f"Golden reconciliation: {summary['golden_reconciliation']}")
    print(f"Moran's I: {summary['moran_i']}")
    print(f"OLS Base R2={summary['ols_base']['r2']} Adj-R2={summary['ols_base']['adj_r2']}")
    print(
        f"OLS Spatial R2={summary['ols_spatial_controlled']['r2']} "
        f"Adj-R2={summary['ols_spatial_controlled']['adj_r2']}"
    )
    print(f"OLS Spatial coefficients: {summary['ols_spatial_controlled']['coefficients']}")
    print(f"Camera health paradox perm_p: busy_vs_quiet={summary['camera_health_paradox']['busy_vs_quiet_perm_p']}, "
          f"inter_vs_mid={summary['camera_health_paradox']['inter_vs_mid_perm_p']}, "
          f"inter_frozen_share={summary['camera_health_paradox']['intersection_share_of_frozen_pct']}%")
    print("Top 5 Upgrade Priority Cameras:")
    for item in summary["top10_upgrade_priority"][:5]:
        print(f"  #{item['rank']} cam {item['camera_id']} ({item['name'][:38]}): score={item['upgrade_priority_score']}, "
              f"traf={item['band_w_mean']}, malls={item['n_mall_500m']}, frozen={item['bridged_frozen']}")


if __name__ == "__main__":
    main()
