import numpy as np
import pandas as pd

from cctv.daylight import light_phase
from cctv.osm import build, number, poi_category, segment_distance
from cctv.weather import build_weather


def test_segment_distance_perpendicular_and_endpoint():
    xs, ys = np.array([0.0, 10.0]), np.array([0.0, 0.0])
    assert segment_distance(5, 3, xs, ys) == 3
    assert segment_distance(13, 4, xs, ys) == 5  # beyond the end: distance to the endpoint
    assert segment_distance(1, 1, np.array([1.0]), np.array([2.0])) == 1  # single-node way


def test_poi_category_and_number():
    assert poi_category({"amenity": "university"}) == "school"
    assert poi_category({"shop": "mall"}) == "mall_market"
    assert poi_category({"railway": "station"}) == "rail_station"
    assert poi_category({"highway": "traffic_signals"}) == "traffic_signals"
    assert poi_category({"highway": "bus_stop"}) == "bus_stop"
    assert poi_category({"amenity": "bench"}) is None
    assert number("3;2") == 3 and number("60 mph") == 60 and np.isnan(number(None))


def test_build_prefers_major_road_and_counts_pois():
    cams = pd.DataFrame({"camera_id": [1], "latitude": [13.75], "longitude": [100.5]})
    d = 0.0001  # ~11 m
    way = lambda hw, lat, extra=None: {"type": "way", "tags": {"highway": hw, **(extra or {})},
                                       "geometry": [{"lat": lat, "lon": 100.49}, {"lat": lat, "lon": 100.51}]}
    roads = {"elements": [way("service", 13.75), way("primary", 13.75 + d, {"lanes": "4", "name": "Rama IV", "bridge": "yes"}),
                          way("residential", 13.75 + 10 * d)]}
    pois = {"elements": [
        {"type": "node", "id": 1, "lat": 13.751, "lon": 100.5, "tags": {"railway": "station"}},
        {"type": "way", "id": 2, "center": {"lat": 13.752, "lon": 100.5}, "tags": {"amenity": "school"}},
        {"type": "node", "id": 3, "lat": 13.80, "lon": 100.5, "tags": {"amenity": "school"}},  # >500 m away
    ]}
    traffic = {"elements": [
        {"type": "node", "id": 4, "lat": 13.7505, "lon": 100.5, "tags": {"highway": "traffic_signals"}},  # ~55 m
        {"type": "node", "id": 5, "lat": 13.753, "lon": 100.5, "tags": {"highway": "bus_stop"}},  # ~334 m
    ]}
    row = build(cams, roads, pois, traffic).iloc[0]
    assert row["road_class"] == "primary" and row["lanes"] == 4 and row["road_name"] == "Rama IV"
    assert row["is_bridge"] == True
    assert row["n_rail_station_500m"] == 1 and row["n_school_500m"] == 1
    assert row["n_traffic_signals_100m"] == 1 and row["n_traffic_signals_500m"] == 1
    assert row["n_bus_stop_500m"] == 1


def test_build_weather_snaps_grid():
    cams = pd.DataFrame({"camera_id": [10], "latitude": [13.751], "longitude": [100.501]})
    hr = pd.Timestamp("2026-08-25 12:00")
    w_df = pd.DataFrame({"glat": [13.75], "glon": [100.50], "hour": [hr], "precipitation_mm": [1.2]})
    out = build_weather(cams, w_df)
    assert len(out) == 1
    assert out.iloc[0]["precipitation_mm"] == 1.2


def test_light_phase():
    sun = pd.DataFrame({"date": [pd.Timestamp("2026-08-25")],
                        "sunrise": [pd.Timestamp("2026-08-25 06:06")], "sunset": [pd.Timestamp("2026-08-25 18:34")],
                        "civil_twilight_begin": [pd.Timestamp("2026-08-25 05:44")],
                        "civil_twilight_end": [pd.Timestamp("2026-08-25 18:56")]})
    ts = pd.Series(pd.to_datetime(["2026-08-25 05:50", "2026-08-25 12:00", "2026-08-25 18:40",
                                   "2026-08-25 20:00", "2026-08-26 12:00"]))
    out = light_phase(ts, sun)
    assert out[:4].tolist() == ["twilight", "day", "twilight", "night"]
    assert pd.isna(out.iloc[4])  # date without daylight data
