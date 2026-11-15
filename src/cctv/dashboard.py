"""BI dashboard: Bangkok CCTV traffic, rain and road context (Streamlit).

Reads data/processed/dashboard/ (from cctv.mart) and data/processed/l640/rain_effect.csv
(from cctv.rain). Raw images are shown in the camera tab when data/raw/cctv_images exists.

    uv run streamlit run src/cctv/dashboard.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[2]
MART = ROOT / "data/processed/dashboard"
EFFECT = ROOT / "data/processed/l640/rain_effect.csv"
RAW = ROOT / "data/raw/cctv_images"
LEVELS = ["dry", "light (0.1-2)", "moderate (2-5)", "heavy (>5)"]
PERIODS = ["morning 6-9", "midday 10-16", "evening 17-19", "late 20-21"]
TIMING = {"rain_now": "Rain in the same hour", "rain_before": "Rain 1 h earlier", "rain_2h_before": "Rain 2 h earlier"}
MEASURE = {"calibrated": "Vehicles (calibrated to hand counts)", "vehicles": "Vehicles (raw detector)",
           "covered": "Share of frame covered"}
DRY, WET = "#c8a052", "#2f6db5"

st.set_page_config(page_title="Bangkok CCTV: rain and traffic", page_icon="🚦", layout="wide")


@st.cache_data
def load():
    snaps = pd.read_parquet(MART / "snapshots.parquet")
    cams = pd.read_parquet(MART / "cameras.parquet")
    effect = pd.read_csv(EFFECT)
    return snaps, cams, effect


def pct_vs_usual(excess: pd.Series) -> float:
    return 100 * float(np.expm1(excess.mean())) if len(excess) else np.nan


snaps, cams, effect = load()
has_osm = "road_class" in cams.columns and cams["road_class"].notna().any()

# ---- sidebar filters (apply to every snapshot-based chart) ----
st.sidebar.header("Filters")
days = sorted(snaps["date"].dt.date.unique())
day_range = st.sidebar.select_slider("Dates", options=days, value=(days[0], days[-1]))
daytype = st.sidebar.multiselect("Day type", ["weekday", "weekend"], default=["weekday", "weekend"])
light = st.sidebar.multiselect("Light", ["day", "twilight", "night"], default=["day", "twilight", "night"],
                               help="From sunrise-sunset.org: day = sunrise to sunset, twilight = civil twilight.")
roads = sorted(cams["road_class"].dropna().unique()) if has_osm else []
road_pick = st.sidebar.multiselect("Road class (OpenStreetMap)", roads, default=roads) if has_osm else []

f = snaps[(snaps["date"].dt.date >= day_range[0]) & (snaps["date"].dt.date <= day_range[1])
          & snaps["daytype"].isin(daytype) & snaps["light"].isin(light)]
if has_osm:
    f = f[f["road_class"].isin(road_pick) | f["road_class"].isna()]
st.sidebar.caption(f"{len(f):,} of {len(snaps):,} snapshots selected")

st.title("Does rain make Bangkok roads more congested?")
st.caption("100 BMA traffic cameras, 25–31 Aug 2026, one image every ~10 min. Vehicles counted with YOLO11-L, "
           "rain from Open-Meteo, road context from OpenStreetMap, daylight from sunrise-sunset.org.")

tab_over, tab_map, tab_rain, tab_road, tab_cam = st.tabs(
    ["Overview", "Map", "Rain vs congestion", "Road context", "Camera explorer"])

# ---- Overview ----
with tab_over:
    heavy = effect[(effect["timing"] == "rain_now") & (effect["rain"] == "heavy (>5)")].iloc[0]
    dry = effect[(effect["timing"] == "rain_now") & (effect["rain"] == "dry")].iloc[0]
    k = st.columns(5)
    k[0].metric("Cameras", f"{f['camera_id'].nunique()}")
    k[1].metric("Snapshots", f"{len(f):,}")
    k[2].metric("Avg vehicles / frame", f"{f['n_calibrated'].mean():.1f}")
    k[3].metric("Snapshots in wet hours", f"{100 * f['wet'].mean():.0f}%")
    k[4].metric("Heavy rain vs dry", f"{heavy['calibrated_%'] - dry['calibrated_%']:+.1f} pts",
                help="Calibrated vehicles, % above the camera's usual for that hour; whole dataset, not filtered.")

    hourly = (f.assign(slot=f["timestamp"].dt.floor("h"))
              .groupby("slot").agg(vehicles=("n_calibrated", "mean"), rain=("rain_now", "mean")).reset_index())
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=hourly["slot"], y=hourly["rain"], name="Rain (mm/h, camera average)",
                marker_color=WET, opacity=0.45, secondary_y=True)
    fig.add_scatter(x=hourly["slot"], y=hourly["vehicles"], name="Vehicles per frame", mode="lines",
                    line=dict(color="#333", width=2), secondary_y=False)
    fig.update_layout(title="Traffic and rain through the week", height=380, legend=dict(orientation="h", y=-0.2),
                      margin=dict(t=50, b=10))
    fig.update_yaxes(title_text="Vehicles per frame", secondary_y=False)
    fig.update_yaxes(title_text="Rain mm/h", secondary_y=True, showgrid=False)
    st.plotly_chart(fig, width="stretch")

    c1, c2 = st.columns(2)
    prof = f.groupby(["hour", "daytype"])["n_calibrated"].mean().reset_index()
    c1.plotly_chart(px.line(prof, x="hour", y="n_calibrated", color="daytype", markers=True,
                            title="Rush-hour profile", labels={"n_calibrated": "Vehicles per frame"}),
                    width="stretch")
    mix = f[["n_car", "n_motorcycle", "n_truck", "n_bus", "n_bicycle"]].sum().rename(lambda c: c[2:]).reset_index()
    mix.columns = ["class", "detections"]
    c2.plotly_chart(px.pie(mix, names="class", values="detections", hole=0.5, title="Vehicle mix (raw detections)"),
                    width="stretch")

# ---- Map ----
with tab_map:
    metric = st.radio("Colour cameras by", ["Average traffic", "Rain effect", "Peak hour"], horizontal=True)
    sel = f.groupby("camera_id").agg(traffic=("n_calibrated", "mean"), snaps=("n_calibrated", "size")).reset_index()
    e = f.groupby(["camera_id", "wet"])["excess_calibrated"].agg(["mean", "size"]).unstack()
    rain_eff = (100 * (np.expm1(e[("mean", True)]) - np.expm1(e[("mean", False)])))
    rain_eff = rain_eff.where((e[("size", True)] >= 10) & (e[("size", False)] >= 10)).rename("rain_effect")
    m = cams.merge(sel, on="camera_id").merge(rain_eff.reset_index(), on="camera_id", how="left")
    color = {"Average traffic": "traffic", "Rain effect": "rain_effect", "Peak hour": "peak_hour"}[metric]
    hover = {c: True for c in ["road_class", "lanes", "n_rail_station_500m", "peak_hour"] if c in m.columns}
    fig = px.scatter_map(
        m, lat="latitude", lon="longitude", color=color, size="traffic", size_max=18, zoom=11, height=600,
        center={"lat": float(m["latitude"].mean()), "lon": float(m["longitude"].mean())},
        hover_name="name", hover_data={"traffic": ":.1f", "rain_effect": ":+.1f", **hover},
        color_continuous_scale="RdBu_r" if color == "rain_effect" else "YlOrRd",
        color_continuous_midpoint=0 if color == "rain_effect" else None, map_style="open-street-map")
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig, width="stretch")
    st.caption("Rain effect = calibrated traffic vs the camera's usual for that hour, wet hours minus dry hours "
               "(percentage points). Cameras with fewer than 10 wet or dry snapshots in the selection are blank.")
    st.dataframe(m.sort_values("traffic", ascending=False)[
        ["name", "traffic", "rain_effect", "peak_hour"] + [c for c in ["road_class", "lanes"] if c in m.columns]]
        .head(15).round(1), hide_index=True, width="stretch")

# ---- Rain vs congestion ----
with tab_rain:
    c1, c2 = st.columns([1, 1])
    timing = c1.selectbox("Rain timing", list(TIMING), format_func=TIMING.get)
    measure = c2.selectbox("Measure", list(MEASURE), format_func=MEASURE.get)
    t = effect[effect["timing"] == timing].set_index("rain").loc[LEVELS].reset_index()
    fig = go.Figure(go.Bar(
        x=t["rain"], y=t[f"{measure}_%"], marker_color=[DRY, "#8fb3df", "#4f8bd0", WET],
        error_y=dict(type="data", array=t[f"{measure}_hi"] - t[f"{measure}_%"],
                     arrayminus=t[f"{measure}_%"] - t[f"{measure}_lo"]),
        text=[f"n={n:,}" for n in t["snapshots"]], textposition="outside"))
    fig.update_layout(title="Traffic vs the camera's usual level, by rain (95% CI over camera-days)",
                      yaxis_title="% above usual", height=420)
    st.plotly_chart(fig, width="stretch")
    st.caption("Whole dataset (sidebar filters do not apply here; the bootstrap CIs come from cctv.rain).")

    c1, c2 = st.columns(2)
    by = (f.groupby(["period", "wet"])["excess_calibrated"].apply(pct_vs_usual).reset_index(name="pct"))
    by["rain"] = by["wet"].map({True: "wet", False: "dry"})
    c1.plotly_chart(px.bar(by, x="period", y="pct", color="rain", barmode="group",
                           category_orders={"period": PERIODS}, color_discrete_map={"dry": DRY, "wet": WET},
                           title="Wet vs dry by time of day", labels={"pct": "% above usual"}),
                    width="stretch")
    bl = f.groupby(["light", "wet"])["excess_calibrated"].apply(pct_vs_usual).reset_index(name="pct")
    bl["rain"] = bl["wet"].map({True: "wet", False: "dry"})
    c2.plotly_chart(px.bar(bl, x="light", y="pct", color="rain", barmode="group",
                           category_orders={"light": ["day", "twilight", "night"]},
                           color_discrete_map={"dry": DRY, "wet": WET},
                           title="Wet vs dry by daylight", labels={"pct": "% above usual"}),
                    width="stretch")
    st.info("Wet evenings look emptier partly because rain on the lens and darkness hide vehicles; "
            "the calibrated measure corrects for this using 1,200 hand-labelled frames, but the late-evening "
            "wet factor rests on few detections.")

# ---- Road context ----
with tab_road:
    if not has_osm:
        st.warning("Run `uv run python -m cctv.osm` then `uv run python -m cctv.mart` to add OpenStreetMap context.")
    else:
        sel = f.groupby("camera_id").agg(traffic=("n_calibrated", "mean")).reset_index()
        r = cams.merge(sel, on="camera_id")
        order = r.groupby("road_class")["road_rank"].first().sort_values().index.tolist()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.box(r, x="road_class", y="traffic", points="all", hover_name="name",
                               category_orders={"road_class": order}, title="Traffic by road class",
                               labels={"traffic": "Vehicles per frame", "road_class": ""}),
                        width="stretch")
        rr = (f.groupby(["road_class", "wet"])["excess_calibrated"].apply(pct_vs_usual)
              .reset_index(name="pct"))
        rr["rain"] = rr["wet"].map({True: "wet", False: "dry"})
        c2.plotly_chart(px.bar(rr, x="road_class", y="pct", color="rain", barmode="group",
                               category_orders={"road_class": order}, color_discrete_map={"dry": DRY, "wet": WET},
                               title="Rain effect by road class", labels={"pct": "% above usual", "road_class": ""}),
                        width="stretch")
        poi = st.selectbox("Nearby places (within 500 m)",
                           ["n_rail_station_500m", "n_school_500m", "n_mall_market_500m", "n_hospital_500m"],
                           format_func=lambda c: c.split("_", 1)[1].rsplit("_", 1)[0].replace("_", " / "))
        st.plotly_chart(px.strip(r, x=poi, y="traffic", hover_name="name", color="road_class",
                                 category_orders={"road_class": order},
                                 title="Traffic vs number of nearby places",
                                 labels={"traffic": "Vehicles per frame", poi: "count within 500 m"}),
                        width="stretch")

# ---- Camera explorer ----
with tab_cam:
    options = cams.sort_values("name")
    cam_id = st.selectbox("Camera", options["camera_id"],
                          format_func=lambda c: f"{c} · {options.set_index('camera_id').at[c, 'name']}")
    info = cams.set_index("camera_id").loc[cam_id]
    cs = f[f["camera_id"] == cam_id].sort_values("timestamp")
    k = st.columns(4)
    k[0].metric("Avg vehicles", f"{cs['n_calibrated'].mean():.1f}" if len(cs) else "–")
    k[1].metric("Peak hour", f"{int(info['peak_hour'])}:00")
    k[2].metric("Road", str(info.get("road_class", "–")) if has_osm else "–")
    k[3].metric("Rain effect (all data)", f"{info['rain_effect_pct']:+.1f} pts" if pd.notna(info["rain_effect_pct"]) else "–")

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=cs["timestamp"], y=cs["rain_now"], name="Rain mm/h", marker_color=WET, opacity=0.4, secondary_y=True)
    fig.add_scatter(x=cs["timestamp"], y=cs["n_calibrated"], name="Vehicles", mode="lines",
                    line=dict(color="#333", width=1.5), secondary_y=False)
    fig.update_layout(height=320, margin=dict(t=20, b=10), legend=dict(orientation="h", y=-0.25))
    st.plotly_chart(fig, width="stretch")

    if len(cs) and RAW.exists():
        pick = st.select_slider("Snapshot", options=list(range(len(cs))), value=len(cs) // 2,
                                format_func=lambda i: cs.iloc[i]["timestamp"].strftime("%a %d %b %H:%M"))
        row = cs.iloc[pick]
        img = RAW / row["path"]
        c1, c2 = st.columns([2, 1])
        if img.exists():
            c1.image(str(img), width="stretch")
        c2.write({"time": row["timestamp"].strftime("%a %d %b %H:%M"), "light": row["light"],
                  "rain mm/h": round(float(row["rain_now"]), 1), "vehicles (raw)": int(row["n_vehicles"]),
                  "vehicles (calibrated)": round(float(row["n_calibrated"]), 1),
                  "cars": int(row["n_car"]), "motorcycles": int(row["n_motorcycle"]),
                  "trucks": int(row["n_truck"]), "buses": int(row["n_bus"])})
