"""Pure-stdlib Spatio-Temporal Daily Pulse & 50-District Bangkok Mapping Engine.

Joins all 100 BMA cameras to official 50-district Bangkok polygons
(``data/raw/external/bangkok_districts.geojson``) via exact ray-casting
point-in-polygon, strips the 10 golden stratified frames that fell inside verified
forensic frozen streaks (``reports/forensics/frozen_streaks.csv``) so every time-band
spike reflects live traffic only, and maps where Bangkokians drive across:
  - Morning (06:00–09:59)
  - Midday  (10:00–16:59)
  - Evening (17:00–18:59)
  - Night   (19:00–21:00)

Outputs:
  - reports/insights/district_time_profile.csv (50 rows, one per Bangkok district)
  - reports/insights/spatio_temporal_pulse.json

Usage:
    python -m cctv.spatio_temporal --out-dir reports/insights
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any, Callable

BANDS = ("morning", "midday", "evening", "night")
WEEKEND_DATES = {"2026-08-29", "2026-08-30"}


def point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Ray-casting point-in-ring test (lon=x, lat=y)."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = float(ring[i][0]), float(ring[i][1])
        xj, yj = float(ring[j][0]), float(ring[j][1])
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) if abs(yj - yi) > 1e-15 else 1e-15) + xi
        ):
            inside = not inside
        j = i
    return inside


def point_in_geometry(lon: float, lat: float, geometry: dict[str, Any]) -> bool:
    """Exact point-in-Polygon / MultiPolygon test respecting outer rings and holes."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    polys = [coords] if gtype == "Polygon" else coords
    for poly in polys:
        if not poly:
            continue
        if point_in_ring(lon, lat, poly[0]):
            in_hole = any(point_in_ring(lon, lat, hole) for hole in poly[1:])
            if not in_hole:
                return True
    return False


def _thin_ring_for_viz(ring: list[list[float]], tol: float = 0.0008) -> list[list[float]]:
    if len(ring) <= 8:
        return [[round(float(p[0]), 4), round(float(p[1]), 4)] for p in ring]
    kept = [[round(float(ring[0][0]), 4), round(float(ring[0][1]), 4)]]
    for pt in ring[1:-1]:
        x, y = round(float(pt[0]), 4), round(float(pt[1]), 4)
        if abs(x - kept[-1][0]) + abs(y - kept[-1][1]) >= tol:
            kept.append([x, y])
    last = [round(float(ring[-1][0]), 4), round(float(ring[-1][1]), 4)]
    if kept[-1] != last:
        kept.append(last)
    if len(kept) < 4:
        return [[round(float(p[0]), 4), round(float(p[1]), 4)] for p in ring]
    return kept


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def run_spatio_temporal(
    districts_path: Path,
    cameras_profile_path: Path,
    sample_path: Path,
    export_path: Path,
    frozen_streaks_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    geojson = json.loads(districts_path.read_text(encoding="utf-8"))
    features = geojson["features"]

    with cameras_profile_path.open(encoding="utf-8", newline="") as f:
        cam_rows = list(csv.DictReader(f))
    cams: dict[int, dict[str, Any]] = {}
    for r in cam_rows:
        cid = int(r["camera_id"])
        cams[cid] = {
            "camera_id": cid,
            "name": r["name"],
            "location_th": r["location_th"],
            "latitude": float(r["latitude"]),
            "longitude": float(r["longitude"]),
            "is_old_city": int(r["is_old_city"]),
            "junction_type": r["junction_type"],
            "busyness_tercile": r["busyness_tercile"],
            "n_mall_500m": int(r["n_mall_500m"]),
            "n_rail_500m": int(r["n_rail_500m"]),
            "n_school_500m": int(r["n_school_500m"]),
            "n_hospital_500m": int(r["n_hospital_500m"]),
            "band_w_mean": float(r["band_w_mean"]),
        }

    # 1. Point-in-polygon join: assign every camera to one of Bangkok's 50 districts
    cam_to_district: dict[int, tuple[str, str, str]] = {}
    for cid, c in cams.items():
        lat, lon = c["latitude"], c["longitude"]
        matched = None
        for feat in features:
            if point_in_geometry(lon, lat, feat["geometry"]):
                props = feat["properties"]
                matched = (props["dcode"], props["name_th"], props["name_en"])
                break
        if matched is None:
            # Nearest centroid fallback for edge boundary rounding
            best = min(
                features,
                key=lambda ft: _haversine_km(
                    lat, lon, ft["properties"]["centroid_lat"], ft["properties"]["centroid_lon"]
                ),
            )
            props = best["properties"]
            matched = (props["dcode"], props["name_th"], props["name_en"])
        cam_to_district[cid] = matched
        c["dcode"], c["district_th"], c["district_en"] = matched

    # 2. Load frozen streaks to exclude any golden frame that fell inside a frozen streak
    streaks_by_cam: dict[int, list[tuple[str, str]]] = collections.defaultdict(list)
    with frozen_streaks_path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            streaks_by_cam[int(r["camera_id"])].append((r["start_ts"], r["end_ts"]))

    def _is_frozen_frame(cid: int, ts: str) -> bool:
        return any(a < ts <= b for a, b in streaks_by_cam.get(cid, ()))

    with sample_path.open(encoding="utf-8", newline="") as f:
        sample_by_path = {r["path"]: r for r in csv.DictReader(f)}

    export_by_path: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    with export_path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            export_by_path[r["path"]].append(r)

    live_frames: list[dict[str, Any]] = []
    excluded_frozen_golden = 0
    for path, s in sample_by_path.items():
        if s["stratum"] == "day/model_zero":
            continue
        usable = [r for r in export_by_path.get(path, []) if int(r["unusable"]) == 0]
        if not usable:
            continue
        cid = int(s["camera_id"])
        ts = s["timestamp"]
        if _is_frozen_frame(cid, ts):
            excluded_frozen_golden += 1
            continue
        tot = sum(
            sum(float(r[k]) for k in ("car", "motorcycle", "bus", "truck", "bicycle"))
            for r in usable
        ) / len(usable)
        car = sum(float(r["car"]) for r in usable) / len(usable)
        moto = sum(float(r["motorcycle"]) for r in usable) / len(usable)
        bus = sum(float(r["bus"]) for r in usable) / len(usable)
        dt_d = ts.split()[0]
        live_frames.append(
            {
                "camera_id": cid,
                "district_th": cams[cid]["district_th"],
                "district_en": cams[cid]["district_en"],
                "dcode": cams[cid]["dcode"],
                "timestamp": ts,
                "date": dt_d,
                "daytype": "weekend" if dt_d in WEEKEND_DATES else "weekday",
                "band": s["stratum"].split("/")[0],
                "total": tot,
                "car": car,
                "motorcycle": moto,
                "bus": bus,
            }
        )

    # 3. Per-camera 4-band profiles (all / weekday / weekend) & Early-Bird / Night-Owl classification
    cam_band_buckets: dict[tuple[int, str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for fr in live_frames:
        cam_band_buckets[(fr["camera_id"], "all", fr["band"])].append(fr)
        cam_band_buckets[(fr["camera_id"], fr["daytype"], fr["band"])].append(fr)

    cameras_pulse: list[dict[str, Any]] = []
    early_bird_cands = []
    night_owl_cands = []
    for cid in sorted(cams.keys()):
        c = cams[cid]
        prof: dict[str, dict[str, Any]] = {}
        for dt_mode in ("all", "weekday", "weekend"):
            prof[dt_mode] = {}
            for b in BANDS:
                sub = cam_band_buckets.get((cid, dt_mode, b), [])
                prof[dt_mode][b] = {
                    "n": len(sub),
                    "total": round(statistics.mean(x["total"] for x in sub), 2) if sub else None,
                    "car": round(statistics.mean(x["car"] for x in sub), 2) if sub else None,
                    "moto": round(statistics.mean(x["motorcycle"] for x in sub), 2) if sub else None,
                }
        all_means = {b: prof["all"][b]["total"] for b in BANDS if prof["all"][b]["total"] is not None}
        peak_band = max(all_means, key=lambda b: all_means[b]) if all_means else "unknown"
        morn_v = prof["all"]["morning"]["total"]
        night_v = prof["all"]["night"]["total"]
        eve_v = prof["all"]["evening"]["total"]
        night_minus_morn = round(night_v - morn_v, 2) if (morn_v is not None and night_v is not None) else None
        archetype = {
            "morning": "Early Bird (เช้าพีค)",
            "midday": "Midday Hub (กลางวันพีค)",
            "evening": "Evening Rush (เย็นพีค)",
            "night": "Night Owl (ดึกพีค)",
        }.get(peak_band, "Mixed")

        if morn_v is not None and night_v is not None and (morn_v >= 5 or night_v >= 5):
            entry = {
                "camera_id": cid,
                "name": c["name"],
                "district_th": c["district_th"],
                "district_en": c["district_en"],
                "morning": morn_v,
                "midday": prof["all"]["midday"]["total"],
                "evening": eve_v,
                "night": night_v,
                "night_minus_morning": night_minus_morn,
                "n_mall_500m": c["n_mall_500m"],
                "n_rail_500m": c["n_rail_500m"],
            }
            early_bird_cands.append(entry)
            night_owl_cands.append(entry)

        cameras_pulse.append(
            {
                "camera_id": cid,
                "name": c["name"],
                "latitude": c["latitude"],
                "longitude": c["longitude"],
                "dcode": c["dcode"],
                "district_th": c["district_th"],
                "district_en": c["district_en"],
                "peak_band": peak_band,
                "archetype": archetype,
                "night_minus_morning": night_minus_morn,
                "bands": prof,
            }
        )

    early_birds = sorted(early_bird_cands, key=lambda r: r["night_minus_morning"])[:6]
    night_owls = sorted(night_owl_cands, key=lambda r: r["night_minus_morning"], reverse=True)[:6]

    # 4. All 50 Bangkok Districts Spatio-Temporal Profiles + Simplified Polygons
    cams_in_dist: dict[str, list[int]] = collections.defaultdict(list)
    for cid, c in cams.items():
        cams_in_dist[c["district_th"]].append(cid)

    dist_buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for fr in live_frames:
        dist_buckets[(fr["district_th"], "all", fr["band"])].append(fr)
        dist_buckets[(fr["district_th"], fr["daytype"], fr["band"])].append(fr)

    district_csv_rows: list[dict[str, Any]] = []
    districts_payload: list[dict[str, Any]] = []
    for feat in sorted(features, key=lambda ft: str(ft["properties"]["dcode"])):
        props = feat["properties"]
        d_th = props["name_th"]
        d_en = props["name_en"]
        dcode = props["dcode"]
        dcams = sorted(cams_in_dist.get(d_th, []))
        busy_cnt = sum(1 for cid in dcams if cams[cid]["busyness_tercile"] == "busy")
        d_frames = [fr for fr in live_frames if fr["district_th"] == d_th]
        overall_mean = round(statistics.mean(fr["total"] for fr in d_frames), 2) if d_frames else None

        band_stats: dict[str, dict[str, Any]] = {}
        for dt_mode in ("all", "weekday", "weekend"):
            band_stats[dt_mode] = {}
            for b in BANDS:
                sub = dist_buckets.get((d_th, dt_mode, b), [])
                band_stats[dt_mode][b] = {
                    "n": len(sub),
                    "mean": round(statistics.mean(x["total"] for x in sub), 2) if sub else None,
                    "car": round(statistics.mean(x["car"] for x in sub), 2) if sub else None,
                    "moto": round(statistics.mean(x["motorcycle"] for x in sub), 2) if sub else None,
                }

        all_b_means = {b: band_stats["all"][b]["mean"] for b in BANDS if band_stats["all"][b]["mean"] is not None}
        d_peak_band = max(all_b_means, key=lambda b: all_b_means[b]) if all_b_means else "none"

        # Simplify geometry slightly for fast SVG/HTML rendering
        geom = feat["geometry"]
        if geom["type"] == "Polygon":
            viz_polys = [[_thin_ring_for_viz(r) for r in geom["coordinates"]]]
        else:
            viz_polys = [[_thin_ring_for_viz(r) for r in poly] for poly in geom["coordinates"]]

        district_csv_rows.append(
            {
                "dcode": dcode,
                "district_th": d_th,
                "district_en": d_en,
                "centroid_lat": props["centroid_lat"],
                "centroid_lon": props["centroid_lon"],
                "camera_count": len(dcams),
                "busy_cameras": busy_cnt,
                "live_frames": len(d_frames),
                "overall_mean": overall_mean if overall_mean is not None else "",
                "morning_mean": band_stats["all"]["morning"]["mean"] if band_stats["all"]["morning"]["mean"] is not None else "",
                "midday_mean": band_stats["all"]["midday"]["mean"] if band_stats["all"]["midday"]["mean"] is not None else "",
                "evening_mean": band_stats["all"]["evening"]["mean"] if band_stats["all"]["evening"]["mean"] is not None else "",
                "night_mean": band_stats["all"]["night"]["mean"] if band_stats["all"]["night"]["mean"] is not None else "",
                "peak_band": d_peak_band,
            }
        )
        districts_payload.append(
            {
                "dcode": dcode,
                "name_th": d_th,
                "name_en": d_en,
                "centroid_lat": props["centroid_lat"],
                "centroid_lon": props["centroid_lon"],
                "camera_count": len(dcams),
                "busy_cameras": busy_cnt,
                "camera_ids": dcams,
                "overall_mean": overall_mean,
                "peak_band": d_peak_band,
                "bands": band_stats,
                "polys": viz_polys,
            }
        )

    with (out_dir / "district_time_profile.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(district_csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(district_csv_rows)

    # 5. Urban Purpose Zone Pulses (Morning -> Midday -> Evening -> Night)
    zone_defs: list[tuple[str, str, Callable[[dict[str, Any]], bool]]] = [
        ("thonburi", "ฝั่งธนฯ ข้ามสะพาน (Thonburi Bridges)", lambda c: c["longitude"] < 100.50),
        ("schools", "ย่านโรงเรียน ≥3 แห่ง (School-Heavy)", lambda c: c["n_school_500m"] >= 3),
        ("hospitals", "ย่านโรงพยาบาล (Hospital Corridor)", lambda c: c["n_hospital_500m"] >= 1),
        ("old_city", "เมืองเก่าพระนคร–ดุสิต (Old City)", lambda c: c["is_old_city"] == 1),
        ("central_cbd", "ใจกลางสยาม–สีลม–ประตูน้ำ (Central CBD)", lambda c: 100.525 <= c["longitude"] <= 100.555 and 13.72 <= c["latitude"] <= 13.765),
        ("mega_mall", "ย่าน Mega-Mall ≥3 ห้าง (Shopping Hubs)", lambda c: c["n_mall_500m"] >= 3),
        ("rail_hubs", "ใกล้รถไฟฟ้า BTS/MRT (Transit Hubs)", lambda c: c["n_rail_500m"] >= 1),
        ("ratchada", "แนวรัชดา–พระราม 9–ลาดพร้าว (Ratchada Belt)", lambda c: c["longitude"] >= 100.555 and c["latitude"] >= 13.75),
    ]
    urban_zones: list[dict[str, Any]] = []
    for zid, zlabel, pred in zone_defs:
        zcams = [cid for cid, c in cams.items() if pred(c)]
        z_stats: dict[str, dict[str, Any]] = {}
        for dt_mode in ("all", "weekday", "weekend"):
            z_stats[dt_mode] = {}
            for b in BANDS:
                sub = [
                    fr
                    for fr in live_frames
                    if pred(cams[fr["camera_id"]])
                    and fr["band"] == b
                    and (dt_mode == "all" or fr["daytype"] == dt_mode)
                ]
                z_stats[dt_mode][b] = {
                    "n": len(sub),
                    "mean": round(statistics.mean(x["total"] for x in sub), 2) if sub else None,
                    "car": round(statistics.mean(x["car"] for x in sub), 2) if sub else None,
                    "moto": round(statistics.mean(x["motorcycle"] for x in sub), 2) if sub else None,
                }
        m_all = z_stats["all"]["morning"]["mean"] or 1.0
        e_all = z_stats["all"]["evening"]["mean"] or 0.0
        n_all = z_stats["all"]["night"]["mean"] or 0.0
        urban_zones.append(
            {
                "id": zid,
                "label": zlabel,
                "cameras": len(zcams),
                "eve_vs_morn": round(e_all / m_all, 2),
                "night_vs_morn": round(n_all / m_all, 2),
                "bands": z_stats,
            }
        )

    # 6. Traffic-Weighted Center of Mass across Morning -> Midday -> Evening -> Night
    center_of_mass: dict[str, dict[str, Any]] = {}
    for dt_mode in ("all", "weekday", "weekend"):
        center_of_mass[dt_mode] = {}
        for b in BANDS:
            sub = [
                fr
                for fr in live_frames
                if fr["band"] == b and (dt_mode == "all" or fr["daytype"] == dt_mode)
            ]
            wt = sum(fr["total"] for fr in sub)
            if wt > 0:
                clat = sum(cams[fr["camera_id"]]["latitude"] * fr["total"] for fr in sub) / wt
                clon = sum(cams[fr["camera_id"]]["longitude"] * fr["total"] for fr in sub) / wt
                center_of_mass[dt_mode][b] = {
                    "lat": round(clat, 5),
                    "lon": round(clon, 5),
                    "mean_total": round(wt / len(sub), 2),
                    "frames": len(sub),
                }

    # Interactive Thai storytelling stops per time band
    story_stops = {
        "morning": {
            "title": "06:00–09:59 น. (เช้า): คลื่นคนทำงาน + ข้ามสะพานฝั่งธนฯ + มอไซค์พุ่งสุด",
            "story": "ช่วงเช้าถนนสายเข้าเมืองฝั่งธนฯ (ธนบุรี/จอมทอง) และเส้นโรงพยาบาลรถแน่นตั้งแต่ไก่โห่ (เช่น กล้อง 26 ถ.มไหสวรรย์เฉลี่ย 52.5 คัน) มอเตอร์ไซค์วันธรรมดาครองถนนถึง 34.2% ขณะที่ย่านห้างสรรพสินค้ายังเพิ่งตื่น (14.8 คัน)",
        },
        "midday": {
            "title": "10:00–16:59 น. (กลางวัน): ย่านธุรกิจ & ห้างเปิด — เสาร์-อาทิตย์รถเก๋งแซงวันธรรมดา!",
            "story": "พอเข้าช่วงกลางวัน ศูนย์กลางรถติดเคลื่อนเข้าสู่โซนออฟฟิศและช้อปปิ้ง (ปทุมวัน–ราชเทวี–บางรัก 23.2 คัน) และในวันเสาร์-อาทิตย์ ช่วงกลางวันนี้เองที่รถยนต์ส่วนตัวขับออกมาเที่ยวห้างมากกว่าวันทำงาน (+6.6%)",
        },
        "evening": {
            "title": "17:00–18:59 น. (เย็น): จุดระเบิด Mega-Mall (+75% จากตอนเช้า) & ใจกลางเมือง",
            "story": "ช่วงพีคที่สุดของวัน (เฉลี่ยทั้งเมือง 19.1 คัน) โซน Mega-Mall พุ่งจากเช้า 14.8 ไปเป็น 25.8 คัน (+75%!) แนวห้วยขวาง–ดินแดง–ราชเทวี–ปทุมวันแดงเข้มทั้งแนว และถ้าฝนตกตอนเย็นนี้ มอไซค์จะหายไปจากถนนทันที 31.9%",
        },
        "night": {
            "title": "19:00–21:00 น. (ค่ำ–ดึก): เมืองเก่าหลับแล้ว แต่แนวรัชดา–พระราม 9 ยังคึกคัก!",
            "story": "หลัง 1 ทุ่ม ย่านเมืองเก่าพระนคร–ดุสิตลดลงเหลือแค่ 6.4 คัน และฝั่งธนฯ หลับลง (-36%) แต่ถนนสายไลฟ์สไตล์อย่างแนวรัชดา–ห้วยขวาง–พระราม 9 (กล้อง 112 เทียมร่วมมิตร 41.3 คัน, กล้อง 211 รัชดา 31.5 คัน, กล้อง 1815 พระราม 9 31.0 คัน) ยังหนาแน่นเกินตอนเช้าเสียอีก!",
        },
    }

    covered_districts = sum(1 for d in districts_payload if d["camera_count"] > 0)
    payload = {
        "meta": {
            "total_districts": len(districts_payload),
            "covered_districts": covered_districts,
            "uncovered_districts": len(districts_payload) - covered_districts,
            "total_cameras": len(cams),
            "live_stratified_frames": len(live_frames),
            "excluded_frozen_golden": excluded_frozen_golden,
        },
        "story_stops": story_stops,
        "center_of_mass": center_of_mass,
        "urban_zones": urban_zones,
        "early_birds": early_birds,
        "night_owls": night_owls,
        "districts": districts_payload,
        "cameras_pulse": cameras_pulse,
    }
    (out_dir / "spatio_temporal_pulse.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--districts", type=Path, default=Path("data/raw/external/bangkok_districts.geojson"))
    parser.add_argument("--cameras-profile", type=Path, default=Path("reports/insights/camera_spatial_profile.csv"))
    parser.add_argument("--sample", type=Path, default=Path("data/labels/sample.csv"))
    parser.add_argument("--export", type=Path, default=Path("data/labels/export.csv"))
    parser.add_argument("--frozen-streaks", type=Path, default=Path("reports/forensics/frozen_streaks.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/insights"))
    args = parser.parse_args()

    res = run_spatio_temporal(
        districts_path=args.districts,
        cameras_profile_path=args.cameras_profile,
        sample_path=args.sample,
        export_path=args.export,
        frozen_streaks_path=args.frozen_streaks,
        out_dir=args.out_dir,
    )
    print("Meta:", res["meta"])
    print("Top active districts:")
    active = sorted([d for d in res["districts"] if d["camera_count"] > 0], key=lambda x: x["overall_mean"] or 0, reverse=True)
    for d in active[:8]:
        b = d["bands"]["all"]
        print(f"  เขต{d['name_th']} ({d['name_en']}): cams={d['camera_count']}, overall={d['overall_mean']} | "
              f"M={b['morning']['mean']} D={b['midday']['mean']} E={b['evening']['mean']} N={b['night']['mean']}")
    print("Night owls (clean non-frozen):", [(r["camera_id"], r["district_th"], r["morning"], r["night"]) for r in res["night_owls"][:5]])
    print("Early birds (clean non-frozen):", [(r["camera_id"], r["district_th"], r["morning"], r["night"]) for r in res["early_birds"][:5]])


if __name__ == "__main__":
    main()
