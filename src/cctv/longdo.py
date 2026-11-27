"""Playwright scraper for Longdo Traffic road incidents, accidents, and traffic index.

Uses Playwright (headless Chromium/Chrome) to interact with the JavaScript SPA at
https://traffic.longdo.com/main/#events (clicking event-category filter buttons to
scrape live road incidents and intercept the event-type dictionary) and navigates
https://traffic.longdo.com/download to download the 2026 historical event archive
and 5-minute Bangkok Traffic Index.

Compact Bangkok caches are stored in data/raw/external/ so subsequent pipeline runs
work offline; pass --refresh to re-scrape with Playwright.

Outputs (data/interim/):
  longdo_events.parquet          Bangkok road incidents during the CCTV study week
  longdo_live_events.parquet     Live/recent incidents scraped from the interactive SPA
  longdo_traffic_index.parquet   5-min & hourly Bangkok Traffic Index for the study week
  longdo_camera_risk.parquet     Per-camera 2026 annual accident/incident density (<=500m, <=1km)

Analysis outputs (with --stage analyze, under data/processed/insights/):
  longdo_validation.csv          CCTV citywide volume vs. Longdo Traffic Index (incl. Mon 31 Aug check)
  longdo_incident_impact.csv     Within-camera excess during nearby road incidents vs. normal hours
  longdo_shock_matches.csv       Detected CCTV traffic shocks matched to Longdo road incidents

    uv run python -m cctv.longdo --refresh
    uv run python -m cctv.longdo --stage analyze
"""

from __future__ import annotations

import argparse
import html
import json
import re
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

LONGDO_MAIN_URL = "https://traffic.longdo.com/main/#events"
LONGDO_DOWNLOAD_URL = "https://traffic.longdo.com/download"
LONGDO_EVENT_FEED_2026 = "https://event.longdo.com/feed/2026"
LONGDO_TRAFFIC_INDEX_2026 = "https://traffic.longdo.com/api/raw/trafficindex/2026"

# Interactive category filter buttons on traffic.longdo.com/main/#events
LIVE_CATEGORY_BUTTONS = ["อุบัติเหตุ", "รถเสีย", "ก่อสร้าง", "ฝนตก", "รถติด"]

# Road-relevant Longdo event type IDs (excludes non-road items like house fires / sales / earthquakes)
ROAD_EVENT_TYPE_IDS = {1, 2, 3, 5, 6, 7, 9, 10, 12, 13, 18, 19}

TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", str(text)))).strip()


def haversine_km_matrix(
    lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray
) -> np.ndarray:
    """Pairwise great-circle distances in km between (N,) and (M,) coordinate arrays."""
    r = 6371.0088
    p1 = np.radians(lat1)[:, None]
    p2 = np.radians(lat2)[None, :]
    dp = p2 - p1
    dl = np.radians(lon2)[None, :] - np.radians(lon1)[:, None]
    a = np.sin(dp / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    return 2.0 * r * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _launch_browser(playwright):
    """Launch headless Chromium, preferring system Chrome to avoid separate binary downloads."""
    try:
        return playwright.chromium.launch(channel="chrome", headless=True)
    except Exception:
        return playwright.chromium.launch(headless=True)


def scrape_longdo_with_playwright(
    cameras: pd.DataFrame,
    start_date: str,
    end_date: str,
    cache_dir: Path,
    bbox_pad: float = 0.05,
) -> dict[str, Path]:
    """Run Playwright against Longdo Traffic SPA & download portal and write compact caches."""
    from playwright.sync_api import sync_playwright

    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "event_types": cache_dir / "longdo_event_types.json",
        "live_events": cache_dir / "longdo_live_events.json",
        "study_week_events": cache_dir / "longdo_events_study_week.csv",
        "camera_risk": cache_dir / "longdo_camera_risk_2026.csv",
        "traffic_index": cache_dir / "longdo_traffic_index_study_week.csv",
    }

    event_types: list[dict] = []
    live_by_eid: dict[str, dict] = {}
    dom_cards_seen = 0

    with sync_playwright() as p:
        browser = _launch_browser(p)
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1280, "height": 900},
            locale="th-TH",
        )
        page = context.new_page()

        # Intercept dynamic XHR responses triggered by interacting with the SPA
        def handle_response(resp):
            nonlocal event_types
            url = resp.url
            if "traffic.longdo.com/geteventtype" in url and resp.status == 200:
                try:
                    event_types = resp.json()
                except Exception:
                    pass
            elif "traffic.longdo.com/event/search/" in url and resp.status == 200:
                try:
                    payload = resp.json()
                    for item in payload.get("item", []):
                        eid = str(item.get("eid", ""))
                        if eid:
                            live_by_eid[eid] = item
                except Exception:
                    pass

        page.on("response", handle_response)

        # --- Stage 1: Interactive SPA scraping on traffic.longdo.com/main/#events ---
        print(f"[playwright] opening {LONGDO_MAIN_URL}", flush=True)
        page.goto(LONGDO_MAIN_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3500)

        for label in LIVE_CATEGORY_BUTTONS:
            btn = page.locator(f"button.taglist:has-text('{label}')").first
            if btn.count() > 0:
                try:
                    btn.click(timeout=5000)
                    page.wait_for_timeout(1800)
                    cards = page.locator(".event-list .event").count()
                    dom_cards_seen += cards
                    print(f"[playwright] clicked '{label}' -> {cards} rendered cards (unique XHR events={len(live_by_eid)})", flush=True)
                except Exception as exc:
                    print(f"[playwright] warning clicking '{label}': {exc}", flush=True)

        # Normalize live events
        live_rows = []
        for item in live_by_eid.values():
            live_rows.append({
                "eid": str(item.get("eid", "")),
                "title": str(item.get("title", "")).strip(),
                "title_en": str(item.get("title_en", "")).strip(),
                "description": strip_html(item.get("comment")),
                "severity": item.get("severity"),
                "contributor": str(item.get("contributor", "")).strip(),
                "latitude": pd.to_numeric(item.get("latitude"), errors="coerce"),
                "longitude": pd.to_numeric(item.get("longitude"), errors="coerce"),
                "start": item.get("start_time"),
                "stop": item.get("stop_time"),
                "createtime": item.get("createtime"),
            })
        paths["event_types"].write_text(json.dumps(event_types, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["live_events"].write_text(
            json.dumps({"dom_cards_seen": dom_cards_seen, "items": live_rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # --- Stage 2: Navigate to traffic.longdo.com/download and download 2026 event archive ---
        print(f"[playwright] opening {LONGDO_DOWNLOAD_URL}", flush=True)
        page.goto(LONGDO_DOWNLOAD_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_csv = Path(tmpdir) / "event2026.csv"
            with page.expect_download(timeout=90000) as dl_info:
                page.locator(f"a[href='{LONGDO_EVENT_FEED_2026}']").click()
            dl_info.value.save_as(tmp_csv)
            print(f"[playwright] downloaded 2026 archive ({tmp_csv.stat().st_size / 1e6:.1f} MB)", flush=True)

            ev_all = pd.read_csv(tmp_csv, encoding="utf-8-sig")

        # Filter to Bangkok bounding box around the 100 CCTV cameras
        lat_min = float(cameras["latitude"].min()) - bbox_pad
        lat_max = float(cameras["latitude"].max()) + bbox_pad
        lon_min = float(cameras["longitude"].min()) - bbox_pad
        lon_max = float(cameras["longitude"].max()) + bbox_pad

        ev_all["latitude"] = pd.to_numeric(ev_all["latitude"], errors="coerce")
        ev_all["longitude"] = pd.to_numeric(ev_all["longitude"], errors="coerce")
        ev_all["type"] = pd.to_numeric(ev_all["type"], errors="coerce").astype("Int64")
        ev_all["start_dt"] = pd.to_datetime(ev_all["start"], errors="coerce")

        bkk_all = ev_all[
            ev_all["latitude"].between(lat_min, lat_max)
            & ev_all["longitude"].between(lon_min, lon_max)
        ].copy()

        # Study-week slice (exact CCTV window)
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1)
        study_week = bkk_all[(bkk_all["start_dt"] >= start_ts) & (bkk_all["start_dt"] < end_ts)].copy()
        study_week.drop(columns=["start_dt"]).to_csv(paths["study_week_events"], index=False)
        print(
            f"[playwright] saved {len(study_week)} Bangkok study-week events ({start_date}..{end_date}) "
            f"out of {len(ev_all)} total 2026 Thailand events",
            flush=True,
        )

        # Annual 2026 per-camera road-incident & accident risk (within 500 m and 1 km)
        road_2026 = bkk_all[bkk_all["type"].isin(ROAD_EVENT_TYPE_IDS)].dropna(subset=["latitude", "longitude"]).copy()
        risk_df = compute_camera_annual_risk(cameras, road_2026)
        risk_df.to_csv(paths["camera_risk"], index=False)

        # --- Stage 3: Fetch 2026 5-minute Bangkok Traffic Index via Playwright session ---
        resp_idx = page.request.get(LONGDO_TRAFFIC_INDEX_2026, timeout=60000)
        if resp_idx.status == 200:
            lines = resp_idx.text().splitlines()
            header = lines[0] if lines else "timestamp,datetime,index"
            keep_dates = {
                (start_ts + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
                for i in range((end_ts - start_ts).days)
            }
            filtered = [header] + [ln for ln in lines[1:] if any(d in ln for d in keep_dates)]
            paths["traffic_index"].write_text("\n".join(filtered) + "\n", encoding="utf-8")
            print(f"[playwright] saved {len(filtered) - 1} 5-min Bangkok Traffic Index rows", flush=True)

        browser.close()

    return paths


def compute_camera_annual_risk(cameras: pd.DataFrame, road_events: pd.DataFrame) -> pd.DataFrame:
    """Count annual road incidents and accidents within 500m and 1km of each camera."""
    cam_lat = cameras["latitude"].to_numpy(dtype=float)
    cam_lon = cameras["longitude"].to_numpy(dtype=float)
    ev_lat = road_events["latitude"].to_numpy(dtype=float)
    ev_lon = road_events["longitude"].to_numpy(dtype=float)
    ev_type = road_events["type"].to_numpy()

    if len(ev_lat) == 0:
        return pd.DataFrame({
            "camera_id": cameras["camera_id"].astype(str),
            "longdo_road_events_500m_2026": 0,
            "longdo_accidents_500m_2026": 0,
            "longdo_breakdowns_500m_2026": 0,
            "longdo_road_events_1km_2026": 0,
            "longdo_accidents_1km_2026": 0,
        })

    # Compute in chunks to keep memory tiny even for 20k+ Bangkok events
    n_cams = len(cameras)
    road_500 = np.zeros(n_cams, dtype=int)
    acc_500 = np.zeros(n_cams, dtype=int)
    brk_500 = np.zeros(n_cams, dtype=int)
    road_1k = np.zeros(n_cams, dtype=int)
    acc_1k = np.zeros(n_cams, dtype=int)

    chunk = 2000
    for i in range(0, len(ev_lat), chunk):
        d = haversine_km_matrix(cam_lat, cam_lon, ev_lat[i:i + chunk], ev_lon[i:i + chunk])
        t = ev_type[i:i + chunk]
        is_acc = (t == 3)[None, :]
        is_brk = (t == 1)[None, :]
        m500 = d <= 0.5
        m1k = d <= 1.0
        road_500 += m500.sum(axis=1)
        acc_500 += (m500 & is_acc).sum(axis=1)
        brk_500 += (m500 & is_brk).sum(axis=1)
        road_1k += m1k.sum(axis=1)
        acc_1k += (m1k & is_acc).sum(axis=1)

    return pd.DataFrame({
        "camera_id": cameras["camera_id"].astype(str).values,
        "longdo_road_events_500m_2026": road_500,
        "longdo_accidents_500m_2026": acc_500,
        "longdo_breakdowns_500m_2026": brk_500,
        "longdo_road_events_1km_2026": road_1k,
        "longdo_accidents_1km_2026": acc_1k,
    })


def build_interim_tables(cameras: pd.DataFrame, cache_dir: Path, interim_dir: Path) -> None:
    """Convert cached Longdo files into clean parquet tables under data/interim/."""
    interim_dir.mkdir(parents=True, exist_ok=True)

    type_map_th: dict[int, str] = {}
    type_map_en: dict[int, str] = {}
    et_path = cache_dir / "longdo_event_types.json"
    if et_path.exists():
        for entry in json.loads(et_path.read_text(encoding="utf-8")):
            tid = int(entry["id"])
            type_map_th[tid] = str(entry.get("name", ""))
            type_map_en[tid] = str(entry.get("name_en", ""))

    # 1. Study-week Bangkok events enriched with nearest CCTV camera
    ev_df = pd.read_csv(cache_dir / "longdo_events_study_week.csv")
    ev_df["eid"] = ev_df["eid"].astype(str)
    ev_df["type_id"] = pd.to_numeric(ev_df["type"], errors="coerce").astype("Int64")
    ev_df["type_th"] = ev_df["type_id"].map(type_map_th).fillna("Other")
    ev_df["type_en"] = ev_df["type_id"].map(type_map_en).fillna("Other")
    ev_df["is_road_event"] = ev_df["type_id"].isin(ROAD_EVENT_TYPE_IDS)
    ev_df["start_dt"] = pd.to_datetime(ev_df["start"], errors="coerce")
    ev_df["stop_dt"] = pd.to_datetime(ev_df["stop"], errors="coerce")
    ev_df["date_str"] = ev_df["start_dt"].dt.strftime("%Y-%m-%d")
    ev_df["hour"] = ev_df["start_dt"].dt.hour

    valid_coords = ev_df["latitude"].notna() & ev_df["longitude"].notna()
    nearest_cam = np.full(len(ev_df), "", dtype=object)
    nearest_km = np.full(len(ev_df), np.nan, dtype=float)
    if valid_coords.any():
        dmat = haversine_km_matrix(
            ev_df.loc[valid_coords, "latitude"].to_numpy(dtype=float),
            ev_df.loc[valid_coords, "longitude"].to_numpy(dtype=float),
            cameras["latitude"].to_numpy(dtype=float),
            cameras["longitude"].to_numpy(dtype=float),
        )
        idx = dmat.argmin(axis=1)
        nearest_cam[valid_coords.to_numpy()] = cameras["camera_id"].astype(str).to_numpy()[idx]
        nearest_km[valid_coords.to_numpy()] = dmat[np.arange(len(idx)), idx]

    ev_df["nearest_camera_id"] = nearest_cam
    ev_df["nearest_camera_km"] = np.round(nearest_km, 3)
    ev_df.to_parquet(interim_dir / "longdo_events.parquet", index=False)

    # 2. Live interactive SPA events
    live_payload = json.loads((cache_dir / "longdo_live_events.json").read_text(encoding="utf-8"))
    live_df = pd.DataFrame(live_payload.get("items", []))
    live_df.to_parquet(interim_dir / "longdo_live_events.parquet", index=False)

    # 3. 5-min Bangkok Traffic Index
    idx_df = pd.read_csv(cache_dir / "longdo_traffic_index_study_week.csv")
    idx_df["dt"] = pd.to_datetime(idx_df["datetime"], errors="coerce")
    idx_df["date_str"] = idx_df["dt"].dt.strftime("%Y-%m-%d")
    idx_df["hour"] = idx_df["dt"].dt.hour
    idx_df["index"] = pd.to_numeric(idx_df["index"], errors="coerce")
    idx_df.to_parquet(interim_dir / "longdo_traffic_index.parquet", index=False)

    # 4. Annual 2026 per-camera risk
    risk_df = pd.read_csv(cache_dir / "longdo_camera_risk_2026.csv")
    risk_df["camera_id"] = risk_df["camera_id"].astype(str)
    risk_df.to_parquet(interim_dir / "longdo_camera_risk.parquet", index=False)

    print(
        f"[longdo] wrote interim parquet tables: "
        f"{len(ev_df)} study-week events ({int(ev_df['is_road_event'].sum())} road-related), "
        f"{len(live_df)} live SPA events, {len(idx_df)} traffic-index rows",
        flush=True,
    )


def analyze_longdo(
    snaps_path: Path,
    shocks_path: Path,
    interim_dir: Path,
    cameras_path: Path,
    out_dir: Path,
    n_perm: int = 2000,
    seed: int = 42,
) -> dict[str, pd.DataFrame]:
    """Cross-validate CCTV data against Longdo Traffic Index, road incidents, and shocks."""
    out_dir.mkdir(parents=True, exist_ok=True)
    snaps = pd.read_parquet(snaps_path)
    snaps["camera_id"] = snaps["camera_id"].astype(str)
    snaps["date_str"] = pd.to_datetime(snaps["timestamp"]).dt.strftime("%Y-%m-%d")
    shocks = pd.read_csv(shocks_path)
    shocks["camera_id"] = shocks["camera_id"].astype(str)
    cams = pd.read_csv(cameras_path)
    cams["camera_id"] = cams["camera_id"].astype(str)

    events = pd.read_parquet(interim_dir / "longdo_events.parquet")
    tidx = pd.read_parquet(interim_dir / "longdo_traffic_index.parquet")

    # 1. Hourly citywide CCTV calibrated volume vs. Longdo Bangkok Traffic Index
    hourly_cctv = (
        snaps.groupby(["date_str", "hour"], as_index=False)
        .agg(
            cctv_mean_cal=("n_calibrated", "mean"),
            cctv_mean_excess=("excess_calibrated", "mean"),
            n_snaps=("n_calibrated", "size"),
            rain_mm=("rain_now", "mean"),
        )
    )
    hourly_idx = (
        tidx.groupby(["date_str", "hour"], as_index=False)
        .agg(longdo_index=("index", "mean"))
    )
    val = hourly_cctv.merge(hourly_idx, on=["date_str", "hour"], how="inner")

    # Compute hourly baseline (usual Mon-Fri / Sat-Sun Longdo index) for Mon 31 Aug comparison
    val["is_weekend"] = pd.to_datetime(val["date_str"]).dt.day_of_week >= 5
    val["longdo_usual"] = val.groupby(["is_weekend", "hour"])["longdo_index"].transform("mean")
    val["longdo_diff_vs_usual"] = val["longdo_index"] - val["longdo_usual"]

    pearson_r = float(val["cctv_mean_cal"].corr(val["longdo_index"], method="pearson"))
    spearman_r = float(val["cctv_mean_cal"].rank().corr(val["longdo_index"].rank(), method="pearson"))

    # Permutation p-value for hourly correlation
    rng = np.random.default_rng(seed)
    x = val["cctv_mean_cal"].to_numpy(dtype=float)
    y = val["longdo_index"].to_numpy(dtype=float)
    x_c = x - x.mean()
    y_c = y - y.mean()
    denom = np.sqrt((x_c ** 2).sum() * (y_c ** 2).sum())
    obs_r = float((x_c * y_c).sum() / denom) if denom > 0 else np.nan
    perm_rs = np.empty(n_perm)
    for k in range(n_perm):
        yp = rng.permutation(y_c)
        perm_rs[k] = (x_c * yp).sum() / denom
    corr_p = float((np.abs(perm_rs) >= abs(obs_r)).mean())

    # Dry vs Wet sensor agreement breakdown
    val["wet"] = val["rain_mm"] > 0
    dry_sub = val[~val["wet"]]
    wet_sub = val[val["wet"]]
    dry_r = float(dry_sub["cctv_mean_cal"].corr(dry_sub["longdo_index"])) if len(dry_sub) > 2 else np.nan
    dry_rho = float(dry_sub["cctv_mean_cal"].rank().corr(dry_sub["longdo_index"].rank())) if len(dry_sub) > 2 else np.nan
    wet_r = float(wet_sub["cctv_mean_cal"].corr(wet_sub["longdo_index"])) if len(wet_sub) > 2 else np.nan
    wet_rho = float(wet_sub["cctv_mean_cal"].rank().corr(wet_sub["longdo_index"].rank())) if len(wet_sub) > 2 else np.nan

    # Wet vs Dry evening Longdo Traffic Index (17-20h)
    eve_sub = val[val["hour"].between(17, 20)]
    dry_eve_idx = float(eve_sub.loc[~eve_sub["wet"], "longdo_index"].mean()) if (~eve_sub["wet"]).any() else np.nan
    wet_eve_idx = float(eve_sub.loc[eve_sub["wet"], "longdo_index"].mean()) if eve_sub["wet"].any() else np.nan

    # Mon 31 Aug evening (17:00-20:00) diagnostic: did Longdo Traffic Index drop like CCTV?
    mon_eve = val[(val["date_str"] == "2026-08-31") & (val["hour"].between(17, 20))]
    other_wk_eve = val[(~val["is_weekend"]) & (val["date_str"] != "2026-08-31") & (val["hour"].between(17, 20))]
    mon_cctv_pct = float((np.exp(mon_eve["cctv_mean_excess"].mean()) - 1.0) * 100.0) if len(mon_eve) else np.nan
    mon_idx_mean = float(mon_eve["longdo_index"].mean()) if len(mon_eve) else np.nan
    other_idx_mean = float(other_wk_eve["longdo_index"].mean()) if len(other_wk_eve) else np.nan
    mon_idx_pct = float((mon_idx_mean / other_idx_mean - 1.0) * 100.0) if other_idx_mean else np.nan

    val_summary = pd.DataFrame([
        {
            "metric": "hourly_cctv_vs_longdo_index",
            "n_hours": len(val),
            "pearson_r": round(pearson_r, 4),
            "spearman_r": round(spearman_r, 4),
            "perm_p": round(corr_p, 4),
            "dry_n_hours": len(dry_sub),
            "dry_pearson_r": round(dry_r, 4) if pd.notna(dry_r) else np.nan,
            "dry_spearman_r": round(dry_rho, 4) if pd.notna(dry_rho) else np.nan,
            "wet_n_hours": len(wet_sub),
            "wet_pearson_r": round(wet_r, 4) if pd.notna(wet_r) else np.nan,
            "wet_spearman_r": round(wet_rho, 4) if pd.notna(wet_rho) else np.nan,
            "dry_eve_longdo_index": round(dry_eve_idx, 2) if pd.notna(dry_eve_idx) else np.nan,
            "wet_eve_longdo_index": round(wet_eve_idx, 2) if pd.notna(wet_eve_idx) else np.nan,
            "mon31_eve_cctv_pct": round(mon_cctv_pct, 2) if pd.notna(mon_cctv_pct) else np.nan,
            "mon31_eve_longdo_index": round(mon_idx_mean, 2) if pd.notna(mon_idx_mean) else np.nan,
            "other_weekday_eve_longdo_index": round(other_idx_mean, 2) if pd.notna(other_idx_mean) else np.nan,
            "mon31_eve_longdo_pct": round(mon_idx_pct, 2) if pd.notna(mon_idx_pct) else np.nan,
        }
    ])
    val_summary.to_csv(out_dir / "longdo_validation.csv", index=False)
    val.to_csv(out_dir / "longdo_hourly_comparison.csv", index=False)

    # 2. Nearby road-incident impact on CCTV camera excess (within 500m and 1km during active window)
    road_ev = events[events["is_road_event"]].dropna(subset=["latitude", "longitude", "start_dt"]).copy()
    road_ev["stop_eff"] = road_ev["stop_dt"].fillna(road_ev["start_dt"] + pd.Timedelta(hours=1))
    # Cap overly long multi-day notices at 3 hours so only active incident windows are tested
    dur = (road_ev["stop_eff"] - road_ev["start_dt"]).dt.total_seconds()
    road_ev.loc[(dur <= 0) | (dur > 6 * 3600), "stop_eff"] = road_ev["start_dt"] + pd.Timedelta(hours=1)

    cam_hour = (
        snaps.groupby(["camera_id", "date_str", "hour"], as_index=False)
        .agg(excess=("excess_calibrated", "mean"), cal_total=("n_calibrated", "mean"), rain_mm=("rain_now", "mean"))
    )
    cam_hour["hour_start"] = pd.to_datetime(cam_hour["date_str"]) + pd.to_timedelta(cam_hour["hour"], unit="h")
    cam_hour["hour_end"] = cam_hour["hour_start"] + pd.Timedelta(hours=1)

    dmat = haversine_km_matrix(
        cams["latitude"].to_numpy(dtype=float),
        cams["longitude"].to_numpy(dtype=float),
        road_ev["latitude"].to_numpy(dtype=float),
        road_ev["longitude"].to_numpy(dtype=float),
    )
    cam_ids = cams["camera_id"].to_numpy()

    impact_rows = []
    for radius_km, label in [(0.5, "within_500m"), (1.0, "within_1km")]:
        # Build set of (camera_id, date_str, hour) exposed to an active road incident
        exposed_keys: set[tuple[str, str, int]] = set()
        acc_keys: set[tuple[str, str, int]] = set()
        ev_starts = road_ev["start_dt"].to_numpy()
        ev_stops = road_ev["stop_eff"].to_numpy()
        ev_types = road_ev["type_id"].to_numpy()
        ci, ei = np.where(dmat <= radius_km)
        for c_idx, e_idx in zip(ci, ei):
            s = pd.Timestamp(ev_starts[e_idx]).floor("h")
            e = pd.Timestamp(ev_stops[e_idx]).floor("h")
            cur = s
            while cur <= e:
                key = (cam_ids[c_idx], cur.strftime("%Y-%m-%d"), int(cur.hour))
                exposed_keys.add(key)
                if ev_types[e_idx] == 3:
                    acc_keys.add(key)
                cur += pd.Timedelta(hours=1)

        keys_col = list(zip(cam_hour["camera_id"], cam_hour["date_str"], cam_hour["hour"]))
        for subset_name, key_set in [("all_road_incidents", exposed_keys), ("accidents_only", acc_keys)]:
            mask = np.array([k in key_set for k in keys_col], dtype=bool)
            n_exp = int(mask.sum())
            if n_exp == 0:
                continue
            # Compare against same-camera non-incident hours
            exp_cams = set(cam_hour.loc[mask, "camera_id"])
            ctrl_mask = (~mask) & cam_hour["camera_id"].isin(exp_cams)
            exp_vals = cam_hour.loc[mask, "excess"].to_numpy(dtype=float)
            ctrl_vals = cam_hour.loc[ctrl_mask, "excess"].to_numpy(dtype=float)
            diff = float(exp_vals.mean() - ctrl_vals.mean())
            pct_diff = float((np.exp(diff) - 1.0) * 100.0)

            # Within-camera permutation test
            sub = cam_hour.loc[mask | ctrl_mask, ["camera_id", "excess"]].copy()
            sub["exp"] = mask[mask | ctrl_mask]
            perm_diffs = np.empty(n_perm)
            groups = [g["excess"].to_numpy(dtype=float) for _, g in sub.groupby("camera_id")]
            n_exps = [int(g["exp"].sum()) for _, g in sub.groupby("camera_id")]
            total_exp = sum(n_exps)
            total_ctrl = len(sub) - total_exp
            for k in range(n_perm):
                s_exp = 0.0
                s_all = 0.0
                for arr, ne in zip(groups, n_exps):
                    s_all += arr.sum()
                    if ne > 0:
                        idx_p = rng.choice(len(arr), size=ne, replace=False)
                        s_exp += arr[idx_p].sum()
                perm_diffs[k] = (s_exp / total_exp) - ((s_all - s_exp) / total_ctrl)
            p_val = float((np.abs(perm_diffs) >= abs(diff)).mean())

            impact_rows.append({
                "radius": label,
                "incident_group": subset_name,
                "n_exposed_cam_hours": n_exp,
                "n_cameras_exposed": len(exp_cams),
                "mean_excess_incident": round(float(exp_vals.mean()), 4),
                "mean_excess_control": round(float(ctrl_vals.mean()), 4),
                "diff_log": round(diff, 4),
                "pct_effect": round(pct_diff, 2),
                "perm_p": round(p_val, 4),
            })

    impact_df = pd.DataFrame(impact_rows)
    impact_df.to_csv(out_dir / "longdo_incident_impact.csv", index=False)

    # 3. Cross-match our 262 detected CCTV traffic shocks against Longdo road incidents (<= 1.0 km, +-1 h)
    cam_coords = cams.set_index("camera_id")[["latitude", "longitude"]]
    shocks_geo = shocks.join(cam_coords, on="camera_id")
    shock_matches = []
    if len(shocks_geo) > 0 and len(road_ev) > 0:
        sdmat = haversine_km_matrix(
            shocks_geo["latitude"].to_numpy(dtype=float),
            shocks_geo["longitude"].to_numpy(dtype=float),
            road_ev["latitude"].to_numpy(dtype=float),
            road_ev["longitude"].to_numpy(dtype=float),
        )
        for si, srow in shocks_geo.reset_index(drop=True).iterrows():
            s_time = pd.Timestamp(srow["date_str"]) + pd.Timedelta(hours=int(srow["hour"]))
            near_idx = np.where(sdmat[si] <= 1.0)[0]
            for ei in near_idx:
                erow = road_ev.iloc[ei]
                # Incident overlaps [s_time - 1h, s_time + 2h]
                if erow["start_dt"] <= s_time + pd.Timedelta(hours=1) and erow["stop_eff"] >= s_time - pd.Timedelta(hours=1):
                    shock_matches.append({
                        "camera_id": srow["camera_id"],
                        "camera_name": srow["name"],
                        "date_str": srow["date_str"],
                        "hour": int(srow["hour"]),
                        "z_score": round(float(srow["z_score"]), 2),
                        "pct_vs_usual": round(float(srow["pct_vs_usual"]), 1),
                        "shock_type": srow["shock_type"],
                        "eid": erow["eid"],
                        "event_type": erow["type_en"],
                        "event_type_th": erow["type_th"],
                        "event_title": erow["title"],
                        "event_start": str(erow["start_dt"]),
                        "distance_km": round(float(sdmat[si, ei]), 3),
                    })

    matches_df = pd.DataFrame(shock_matches)
    if len(matches_df) > 0:
        matches_df = matches_df.sort_values(["distance_km", "z_score"], key=lambda s: s.abs() if s.name == "z_score" else s)
    matches_df.to_csv(out_dir / "longdo_shock_matches.csv", index=False)

    # 4. Annual 2026 accident-risk statistical tests (OSM geometry, CCTV volume, Traffic DNA)
    risk_rows = []
    risk_pq = interim_dir / "longdo_camera_risk.parquet"
    osm_pq = interim_dir / "osm_context.parquet"
    dna_pq = Path("data/processed/dna/camera_dna.parquet")
    if risk_pq.exists():
        risk = pd.read_parquet(risk_pq)
        risk["camera_id"] = risk["camera_id"].astype(str)
        cam_vol = snaps.groupby("camera_id", as_index=False).agg(mean_cal=("n_calibrated", "mean"))
        rm = risk.merge(cam_vol, on="camera_id", how="inner")
        if osm_pq.exists():
            osm = pd.read_parquet(osm_pq)
            osm["camera_id"] = osm["camera_id"].astype(str)
            rm = rm.merge(osm, on="camera_id", how="left")
        if dna_pq.exists():
            dna = pd.read_parquet(dna_pq)
            dna["camera_id"] = dna["camera_id"].astype(str)
            rm = rm.merge(dna[["camera_id", "cluster_id"]], on="camera_id", how="left")

        def _spearman_perm(x_s: pd.Series, y_s: pd.Series) -> tuple[float, float]:
            valid = x_s.notna() & y_s.notna()
            if valid.sum() < 4:
                return np.nan, np.nan
            xr = x_s[valid].rank().to_numpy(dtype=float)
            yr = y_s[valid].rank().to_numpy(dtype=float)
            xc, yc = xr - xr.mean(), yr - yr.mean()
            den = np.sqrt((xc ** 2).sum() * (yc ** 2).sum())
            if den <= 0:
                return np.nan, np.nan
            obs = float((xc * yc).sum() / den)
            cnt = sum(abs((xc * rng.permutation(yc)).sum() / den) >= abs(obs) for _ in range(n_perm))
            return obs, cnt / n_perm

        for feat, label in [
            ("is_bridge", "bridge_vs_surface_accidents_500m"),
            ("mean_cal", "cctv_volume_vs_accidents_500m"),
            ("n_rail_station_500m", "rail_station_vs_accidents_500m"),
            ("n_traffic_signals_100m", "signals_vs_accidents_500m"),
        ]:
            if feat in rm.columns:
                rho, p = _spearman_perm(pd.to_numeric(rm[feat], errors="coerce"), rm["longdo_accidents_500m_2026"])
                extra = ""
                if feat == "is_bridge" and rm["is_bridge"].notna().any():
                    g = rm.groupby("is_bridge")["longdo_accidents_500m_2026"].agg(["count", "mean", "median"])
                    if True in g.index and False in g.index:
                        extra = (
                            f"bridge_mean={g.loc[True, 'mean']:.1f} (med={g.loc[True, 'median']:.0f}, n={int(g.loc[True, 'count'])}) "
                            f"vs surface_mean={g.loc[False, 'mean']:.1f} (med={g.loc[False, 'median']:.0f}, n={int(g.loc[False, 'count'])})"
                        )
                risk_rows.append({
                    "test_name": label, "test_type": "spearman_perm",
                    "statistic": round(rho, 4) if pd.notna(rho) else np.nan,
                    "perm_p": round(p, 4) if pd.notna(p) else np.nan,
                    "detail": extra,
                })

        if "cluster_id" in rm.columns and rm["cluster_id"].nunique() >= 2:
            sub_dna = rm.dropna(subset=["cluster_id"]).copy()
            grp = sub_dna["cluster_id"].to_numpy()
            n_g = len(sub_dna)
            for col, label in [
                ("longdo_road_events_500m_2026", "dna_kw_road_events_500m"),
                ("longdo_accidents_1km_2026", "dna_kw_accidents_1km"),
                ("longdo_accidents_500m_2026", "dna_kw_accidents_500m"),
            ]:
                ranks = sub_dna[col].rank().to_numpy(dtype=float)
                def _kw(g_arr):
                    s = 0.0
                    for u in np.unique(g_arr):
                        r_u = ranks[g_arr == u]
                        s += (r_u.sum() ** 2) / len(r_u)
                    return 12.0 / (n_g * (n_g + 1)) * s - 3.0 * (n_g + 1)
                obs_h = float(_kw(grp))
                p_h = float(sum(_kw(rng.permutation(grp)) >= obs_h for _ in range(n_perm)) / n_perm)
                means = sub_dna.groupby("cluster_id")[col].mean().to_dict()
                detail = ", ".join(f"c{int(k)}={v:.1f}" for k, v in sorted(means.items()))
                risk_rows.append({
                    "test_name": label, "test_type": "kruskal_wallis_perm",
                    "statistic": round(obs_h, 3), "perm_p": round(p_h, 4), "detail": detail,
                })

    risk_tests_df = pd.DataFrame(risk_rows)
    risk_tests_df.to_csv(out_dir / "longdo_accident_risk.csv", index=False)

    print(
        f"[longdo-analyze] CCTV vs Longdo Index: r={pearson_r:.3f}, rho={spearman_r:.3f} (p={corr_p:.4f}) "
        f"[dry rho={dry_rho:.3f} vs wet rho={wet_rho:.3f}]; "
        f"Mon 31 Aug eve: CCTV {mon_cctv_pct:+.1f}% vs Longdo Index {mon_idx_pct:+.1f}% "
        f"({mon_idx_mean:.2f} vs {other_idx_mean:.2f}); "
        f"shock matches (<=1km, +-1h): {len(matches_df)}",
        flush=True,
    )
    return {
        "validation": val_summary,
        "impact": impact_df,
        "shock_matches": matches_df,
        "accident_risk": risk_tests_df,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=["scrape", "analyze", "all"], default="scrape")
    parser.add_argument("--cameras", default="data/raw/cctv_info.csv")
    parser.add_argument("--images", default="data/interim/images.parquet")
    parser.add_argument("--cache", default="data/raw/external")
    parser.add_argument("--interim", default="data/interim")
    parser.add_argument("--snaps", default="data/processed/l640/rain_snapshots.parquet")
    parser.add_argument("--shocks", default="data/processed/audit/traffic_shocks.csv")
    parser.add_argument("--out", default="data/processed/insights")
    parser.add_argument("--refresh", action="store_true", help="re-scrape Longdo Traffic with Playwright")
    args = parser.parse_args()

    cache_dir = Path(args.cache)
    interim_dir = Path(args.interim)
    cameras = pd.read_csv(args.cameras)
    cameras["camera_id"] = cameras["camera_id"].astype(str)

    if args.stage in ("scrape", "all"):
        required_cache = [
            cache_dir / "longdo_event_types.json",
            cache_dir / "longdo_live_events.json",
            cache_dir / "longdo_events_study_week.csv",
            cache_dir / "longdo_camera_risk_2026.csv",
            cache_dir / "longdo_traffic_index_study_week.csv",
        ]
        if args.refresh or not all(p.exists() for p in required_cache):
            images = pd.read_parquet(args.images, columns=["timestamp"])
            start_date = images["timestamp"].min().strftime("%Y-%m-%d")
            end_date = images["timestamp"].max().strftime("%Y-%m-%d")
            scrape_longdo_with_playwright(cameras, start_date, end_date, cache_dir)
        build_interim_tables(cameras, cache_dir, interim_dir)

    if args.stage in ("analyze", "all"):
        analyze_longdo(
            snaps_path=Path(args.snaps),
            shocks_path=Path(args.shocks),
            interim_dir=interim_dir,
            cameras_path=Path(args.cameras),
            out_dir=Path(args.out),
        )


if __name__ == "__main__":
    main()
