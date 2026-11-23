import cv2
import numpy as np
import pandas as pd

from cctv.audit import audit_frames, detect_shocks
from cctv.insights import compute_rain_vulnerability, compute_spatial_sync, compute_tidal_flow


def test_audit_frames_catches_whiteout_and_watermark_frozen(tmp_path):
    cam_dir = tmp_path / "10"
    cam_dir.mkdir()
    rng = np.random.default_rng(1)
    base = rng.integers(40, 180, size=(60, 80), dtype=np.uint8)
    with_clock = base.copy()
    with_clock[:4, :30] = 255  # simulated top-left clock watermark change only
    white = np.full((60, 80), 255, dtype=np.uint8)
    changed = rng.integers(20, 220, size=(60, 80), dtype=np.uint8)

    paths = ["10/f0.png", "10/f1.png", "10/f2.png", "10/f3.png"]
    for p, img in zip(paths, [base, with_clock, white, changed]):
        cv2.imwrite(str(tmp_path / p), img)

    def stats(img):
        return float(img.mean()), float(img.std()), float(cv2.Laplacian(img, cv2.CV_64F).var())

    rows = []
    ts0 = pd.Timestamp("2026-08-25 07:00")
    for i, (p, img) in enumerate(zip(paths, [base, with_clock, white, changed])):
        b, c, s = stats(img)
        rows.append({
            "camera_id": "10", "path": p, "timestamp": ts0 + pd.Timedelta(minutes=10 * i),
            "readable": True, "frozen": False, "brightness": b, "contrast": c, "sharpness": s,
        })
    # Make f1 pass candidate metadata tolerances while differing in top watermark only
    rows[1]["brightness"] = rows[0]["brightness"] + 0.1
    rows[1]["contrast"] = rows[0]["contrast"] + 0.1
    rows[1]["sharpness"] = rows[0]["sharpness"] + 1.0

    fa, health, _ = audit_frames(pd.DataFrame(rows), tmp_path)
    fa = fa.set_index("path")
    assert not fa.at["10/f0.png", "visual_frozen"] and fa.at["10/f0.png", "usable"]
    assert fa.at["10/f1.png", "visual_frozen"] and fa.at["10/f1.png", "center_mad"] < 1.0 and not fa.at["10/f1.png", "usable"]
    assert fa.at["10/f2.png", "blank"] and fa.at["10/f2.png", "whiteout"] and not fa.at["10/f2.png", "usable"]
    assert fa.at["10/f3.png", "usable"]
    assert int(health.iloc[0]["blank_frames"]) == 1
    assert int(health.iloc[0]["visual_frozen_frames"]) == 1


def test_detect_shocks_separates_citywide_and_localized():
    info = pd.DataFrame({
        "camera_id": [1, 2, 3, 4, 5, 6, 7, 8],
        "location": [f"L{i}" for i in range(1, 9)],
        "location_en": [f"Cam {i}" for i in range(1, 9)],
        "latitude": [13.750, 13.752, 13.850, 13.852, 13.860, 13.862, 13.870, 13.872],
        "longitude": [100.500, 100.500, 100.600, 100.600, 100.610, 100.610, 100.620, 100.620],
    })
    rows = []
    for day in range(25, 30):
        for hr in [8, 9, 10]:
            for rep in range(3):
                for cid in range(1, 9):
                    exc = 0.0
                    # Localized shock at camera 1 only on Aug 26 09:00
                    if cid == 1 and day == 26 and hr == 9:
                        exc = 0.9
                    # Citywide shock across all 8 cameras on Aug 28 10:00
                    if day == 28 and hr == 10:
                        exc = -0.8
                    rows.append({
                        "camera_id": cid,
                        "timestamp": pd.Timestamp(f"2026-08-{day:02d} {hr:02d}:{rep*10:02d}"),
                        "hour": hr, "excess_calibrated": exc, "n_calibrated": 10.0, "n_vehicles": 10,
                        "rain_now": 0.0, "wet": False, "brightness": 120.0, "sharpness": 1000.0,
                        "path": f"{cid}/{day}_{hr}_{rep}.jpg",
                    })
    shocks, _, _ = detect_shocks(pd.DataFrame(rows), info, z_thresh=2.0)
    loc = shocks[(shocks["camera_id"] == 1) & (shocks["date_str"] == "2026-08-26")]
    city = shocks[shocks["date_str"] == "2026-08-28"]
    assert len(loc) == 1 and loc.iloc[0]["shock_type"] == "localized_shock"
    assert len(city) == 8 and (city["shock_type"] == "citywide_shock").all()


def test_rain_vulnerability_recovers_synthetic_interaction():
    rng = np.random.default_rng(7)
    osm = pd.DataFrame({
        "camera_id": [1, 2, 3, 4],
        "n_traffic_signals_100m": [1, 1, 0, 0],
        "is_bridge": [False, False, True, True],
        "n_rail_station_500m": [0, 0, 1, 1],
        "road_class": ["primary", "primary", "secondary", "secondary"],
    })
    rows = []
    for day in range(25, 31):
        for hr in [8, 9, 10, 11]:
            is_heavy = (day == 27 and hr == 9) or (day == 29 and hr == 10)
            for cid in [1, 2, 3, 4]:
                # Signalized (1,2) spikes +0.30 log-excess in heavy rain; mid-block (3,4) stays ~0
                base = 0.30 if (is_heavy and cid in (1, 2)) else 0.0
                rows.append({
                    "camera_id": cid,
                    "timestamp": pd.Timestamp(f"2026-08-{day:02d} {hr:02d}:00"),
                    "rain_now": 8.0 if is_heavy else 0.0,
                    "wet": is_heavy,
                    "excess_calibrated": base + float(rng.normal(0, 0.02)),
                })
    vuln = compute_rain_vulnerability(pd.DataFrame(rows), osm, dna=None, n_boot=300, seed=403)
    sig_row = vuln[vuln["factor"] == "signalized_100m"].iloc[0]
    assert sig_row["did_pts"] > 15.0
    assert sig_row["boot_p"] < 0.05


def test_tidal_flow_detects_am_pm_reversal():
    info = pd.DataFrame({
        "camera_id": [10, 20],
        "location": ["Inbound", "Outbound"],
        "location_en": ["Bridge In", "Bridge Out"],
        "location_detail_en": ["Inbound", "Outbound"],
        "latitude": [13.7500, 13.75015],  # ~17m apart
        "longitude": [100.5000, 100.5000],
    })
    rows = []
    for day in range(25, 30):  # Tue-Sat -> Tue-Fri are weekdays (25..28) + Mon 31
        for hr in range(6, 21):
            for cid in [10, 20]:
                # Cam 10 peaks AM (20 vs 5), Cam 20 peaks PM (20 vs 5)
                if cid == 10:
                    cnt = 20.0 if hr in [6, 7, 8, 9] else (5.0 if hr in [16, 17, 18, 19] else 10.0)
                else:
                    cnt = 5.0 if hr in [6, 7, 8, 9] else (20.0 if hr in [16, 17, 18, 19] else 10.0)
                rows.append({
                    "camera_id": cid,
                    "timestamp": pd.Timestamp(f"2026-08-{day:02d} {hr:02d}:10"),
                    "daytype": "weekday",
                    "hour": hr,
                    "n_calibrated": cnt,
                })
    pairs, hourly = compute_tidal_flow(pd.DataFrame(rows), info, max_dist_m=100.0, n_perm=500, seed=403)
    assert len(pairs) == 1
    row = pairs.iloc[0]
    assert row["reverses_sign"]
    assert row["tidal_swing"] > 0.2
    assert row["p_value"] < 0.01
    assert len(hourly) == 15


def test_spatial_sync_mantel_detects_local_correlation():
    rng = np.random.default_rng(11)
    # Two distant clusters of 4 cameras each (within-cluster <=0.4 km, between-cluster ~23 km)
    info = pd.DataFrame({
        "camera_id": [1, 2, 3, 4, 5, 6, 7, 8],
        "location": [f"L{i}" for i in range(1, 9)],
        "location_en": [f"L{i}" for i in range(1, 9)],
        "latitude": [13.750, 13.751, 13.752, 13.753, 13.900, 13.901, 13.902, 13.903],
        "longitude": [100.500, 100.500, 100.500, 100.500, 100.650, 100.650, 100.650, 100.650],
    })
    rows = []
    for day in range(25, 31):
        for hr in range(6, 21):
            sig_south = float(rng.normal(0, 0.5))
            sig_north = float(rng.normal(0, 0.5))
            vals = {
                **{cid: sig_south + float(rng.normal(0, 0.05)) for cid in (1, 2, 3, 4)},
                **{cid: sig_north + float(rng.normal(0, 0.05)) for cid in (5, 6, 7, 8)},
            }
            for cid, val in vals.items():
                rows.append({
                    "camera_id": cid,
                    "timestamp": pd.Timestamp(f"2026-08-{day:02d} {hr:02d}:15"),
                    "excess_calibrated": val,
                })
    decay, stests, links = compute_spatial_sync(
        pd.DataFrame(rows), info, max_link_km=2.0, n_mantel=500, n_pair_perm=200, seed=403
    )
    st = stests.set_index("test_name")
    assert st.at["mantel_near_vs_far", "observed"] > 0.5
    assert st.at["mantel_near_vs_far", "p_value"] < 0.05
    assert len(links) == 12 and (links["local_r"] > 0.5).all()
