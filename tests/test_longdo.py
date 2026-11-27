import json
import numpy as np
import pandas as pd

from cctv.longdo import (
    analyze_longdo,
    build_interim_tables,
    compute_camera_annual_risk,
    haversine_km_matrix,
    strip_html,
)


def test_strip_html_and_haversine():
    assert strip_html("<p>อุบัติเหตุ&nbsp;<b>ถนนพระราม 9</b></p>") == "อุบัติเหตุ ถนนพระราม 9"
    d = haversine_km_matrix(
        np.array([13.7500]), np.array([100.5000]),
        np.array([13.7500, 13.7590]), np.array([100.5000, 100.5000]),
    )
    assert d[0, 0] == 0.0
    assert 0.95 < d[0, 1] < 1.05


def test_longdo_offline_build_and_analysis(tmp_path):
    cache_dir = tmp_path / "external"
    interim_dir = tmp_path / "interim"
    out_dir = tmp_path / "insights"
    cache_dir.mkdir()

    cams = pd.DataFrame({
        "camera_id": ["10", "20"],
        "latitude": [13.7500, 13.8000],
        "longitude": [100.5000, 100.5500],
    })
    cams_path = tmp_path / "cctv_info.csv"
    cams.to_csv(cams_path, index=False)

    (cache_dir / "longdo_event_types.json").write_text(json.dumps([
        {"id": 3, "name": "อุบัติเหตุ", "name_en": "Accident", "severity": 3},
        {"id": 15, "name": "เพลิงไหม้", "name_en": "Fire", "severity": 3},
    ]), encoding="utf-8")
    (cache_dir / "longdo_live_events.json").write_text(json.dumps({
        "dom_cards_seen": 1,
        "items": [{"eid": "999", "title": "อุบัติเหตุ", "latitude": 13.7501, "longitude": 100.5001}],
    }), encoding="utf-8")

    ev = pd.DataFrame([
        {
            "eid": "101", "title": "อุบัติเหตุ แยกทดสอบ", "title_en": "Accident",
            "description": "desc", "description_en": "",
            "latitude": 13.7505, "longitude": 100.5000, "type": 3,
            "start": "2026-08-27 18:30:00", "stop": "2026-08-27 19:30:00", "contributor": "test",
        },
        {
            "eid": "102", "title": "เพลิงไหม้บ้าน", "title_en": "Fire",
            "description": "desc", "description_en": "",
            "latitude": 13.8005, "longitude": 100.5500, "type": 15,
            "start": "2026-08-27 10:00:00", "stop": "2026-08-27 11:00:00", "contributor": "test",
        },
    ])
    ev.to_csv(cache_dir / "longdo_events_study_week.csv", index=False)
    risk = compute_camera_annual_risk(cams, ev[ev["type"] == 3])
    risk.to_csv(cache_dir / "longdo_camera_risk_2026.csv", index=False)
    assert int(risk.loc[risk["camera_id"] == "10", "longdo_accidents_500m_2026"].iloc[0]) == 1
    assert int(risk.loc[risk["camera_id"] == "20", "longdo_accidents_500m_2026"].iloc[0]) == 0

    idx_rows = []
    snaps_rows = []
    for day in ["2026-08-27", "2026-08-31"]:
        for hr in [8, 9, 17, 18, 19]:
            idx_val = 6.5 if (day == "2026-08-31" and hr >= 17) else (2.0 + 0.3 * hr)
            idx_rows.append({"timestamp": 0, "datetime": f"{day}T{hr:02d}:00", "index": idx_val})
            for cid in ["10", "20"]:
                exc = -0.6 if (cid == "10" and day == "2026-08-27" and hr == 19) else 0.0
                snaps_rows.append({
                    "camera_id": cid,
                    "timestamp": pd.Timestamp(f"{day} {hr:02d}:15:00"),
                    "hour": hr,
                    "n_calibrated": 5.0 + hr,
                    "excess_calibrated": exc,
                    "rain_now": 0.0,
                })
    pd.DataFrame(idx_rows).to_csv(cache_dir / "longdo_traffic_index_study_week.csv", index=False)

    build_interim_tables(cams, cache_dir, interim_dir)
    ev_pq = pd.read_parquet(interim_dir / "longdo_events.parquet")
    assert len(ev_pq) == 2
    assert ev_pq.loc[ev_pq["eid"] == "101", "nearest_camera_id"].iloc[0] == "10"
    assert bool(ev_pq.loc[ev_pq["eid"] == "101", "is_road_event"].iloc[0]) is True
    assert bool(ev_pq.loc[ev_pq["eid"] == "102", "is_road_event"].iloc[0]) is False

    snaps_path = tmp_path / "rain_snapshots.parquet"
    pd.DataFrame(snaps_rows).to_parquet(snaps_path, index=False)
    shocks_path = tmp_path / "traffic_shocks.csv"
    pd.DataFrame([{
        "camera_id": "10", "date_str": "2026-08-27", "hour": 19,
        "z_score": -3.1, "pct_vs_usual": -45.0, "shock_type": "localized_shock", "name": "Test Cam",
    }]).to_csv(shocks_path, index=False)

    res = analyze_longdo(snaps_path, shocks_path, interim_dir, cams_path, out_dir, n_perm=200, seed=1)
    assert len(res["validation"]) == 1
    assert len(res["shock_matches"]) == 1
    assert res["shock_matches"].iloc[0]["eid"] == "101"
