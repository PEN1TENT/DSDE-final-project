"""BI dashboard: Bangkok CCTV traffic, rain, Traffic DNA and road context (Streamlit).

Reads data/processed/dashboard/ (from cctv.mart), data/processed/l640/rain_effect.csv
(from cctv.rain) and data/processed/dna/ (from cctv.dna). Raw images are shown in the
camera tab when data/raw/cctv_images exists.

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
DNA = ROOT / "data/processed/dna"
INSIGHTS = ROOT / "data/processed/insights"
AUDIT = ROOT / "data/processed/audit"
RAW = ROOT / "data/raw/cctv_images"
LEVELS = ["dry", "light (0.1-2)", "moderate (2-5)", "heavy (>5)"]
PERIODS = ["morning 6-9", "midday 10-16", "evening 17-19", "late 20-21"]
TIMING = {"rain_now": "Rain in the same hour", "rain_before": "Rain 1 h earlier", "rain_2h_before": "Rain 2 h earlier"}
MEASURE = {"calibrated": "Vehicles (calibrated to hand counts)", "vehicles": "Vehicles (raw detector)",
           "covered": "Share of frame covered"}
DRY, WET = "#c8a052", "#2f6db5"
ARCH_COLORS = {
    "All-day urban & retail": "#2a78d6",
    "Evening-peak office / outbound": "#eb6834",
    "Morning-commute arterial": "#1baf7a",
}

st.set_page_config(page_title="Bangkok CCTV: rain and traffic", page_icon="🚦", layout="wide")


@st.cache_data
def load():
    snaps = pd.read_parquet(MART / "snapshots.parquet")
    cams = pd.read_parquet(MART / "cameras.parquet")
    effect = pd.read_csv(EFFECT)
    dna_tables = {}
    if (DNA / "significance_tests.csv").exists():
        dna_tables["sel"] = pd.read_csv(DNA / "model_selection.csv")
        dna_tables["profs"] = pd.read_csv(DNA / "cluster_profiles.csv")
        dna_tables["sig"] = pd.read_csv(DNA / "significance_tests.csv")
        dna_tables["hourly"] = pd.read_parquet(DNA / "hourly_archetypes.parquet")
    ins_tables = {}
    if (INSIGHTS / "rain_vulnerability.csv").exists():
        ins_tables["vuln"] = pd.read_csv(INSIGHTS / "rain_vulnerability.csv")
        ins_tables["tidal_pairs"] = pd.read_csv(INSIGHTS / "tidal_pairs.csv")
        ins_tables["tidal_hourly"] = pd.read_parquet(INSIGHTS / "tidal_hourly.parquet")
        ins_tables["decay"] = pd.read_csv(INSIGHTS / "distance_decay.csv")
        ins_tables["spatial_tests"] = pd.read_csv(INSIGHTS / "spatial_tests.csv")
        ins_tables["links"] = pd.read_csv(INSIGHTS / "corridor_links.csv")
    audit_tables = {}
    if (AUDIT / "camera_health.csv").exists():
        audit_tables["health"] = pd.read_csv(AUDIT / "camera_health.csv")
        audit_tables["outages"] = pd.read_csv(AUDIT / "hourly_outages.csv")
    if (AUDIT / "traffic_shocks.csv").exists():
        audit_tables["shocks"] = pd.read_csv(AUDIT / "traffic_shocks.csv")
        audit_tables["daily_eve"] = pd.read_csv(AUDIT / "daily_evening_audit.csv")
        audit_tables["mon31"] = pd.read_csv(AUDIT / "mon31_hourly.csv")
    return snaps, cams, effect, dna_tables, ins_tables, audit_tables


def pct_vs_usual(excess: pd.Series) -> float:
    return 100 * float(np.expm1(excess.mean())) if len(excess) else np.nan


snaps, cams, effect, dna_tables, ins_tables, audit_tables = load()
has_osm = "road_class" in cams.columns and cams["road_class"].notna().any()
has_dna = "archetype" in snaps.columns and snaps["archetype"].notna().any()

# ---- sidebar filters (apply to every snapshot-based chart) ----
st.sidebar.header("Filters")
days = sorted(snaps["date"].dt.date.unique())
day_range = st.sidebar.select_slider("Dates", options=days, value=(days[0], days[-1]))
daytype = st.sidebar.multiselect("Day type", ["weekday", "weekend"], default=["weekday", "weekend"])
light = st.sidebar.multiselect("Light", ["day", "twilight", "night"], default=["day", "twilight", "night"],
                               help="From sunrise-sunset.org: day = sunrise to sunset, twilight = civil twilight.")
roads = sorted(cams["road_class"].dropna().unique()) if has_osm else []
road_pick = st.sidebar.multiselect("Road class (OpenStreetMap)", roads, default=roads) if has_osm else []
arches = sorted(cams["archetype"].dropna().unique()) if has_dna else []
arch_pick = st.sidebar.multiselect("Archetype (Traffic DNA)", arches, default=arches) if has_dna else []

f = snaps[(snaps["date"].dt.date >= day_range[0]) & (snaps["date"].dt.date <= day_range[1])
          & snaps["daytype"].isin(daytype) & snaps["light"].isin(light)]
if has_osm:
    f = f[f["road_class"].isin(road_pick) | f["road_class"].isna()]
if has_dna:
    f = f[f["archetype"].isin(arch_pick) | f["archetype"].isna()]
st.sidebar.caption(f"{len(f):,} of {len(snaps):,} snapshots selected")

st.title("Does rain make Bangkok roads more congested?")
st.caption("100 BMA traffic cameras, 25–31 Aug 2026, one image every ~10 min. Vehicles counted with YOLO11-L, "
           "rain from Open-Meteo, road context from OpenStreetMap, daylight from sunrise-sunset.org.")

tab_over, tab_map, tab_rain, tab_dna, tab_vuln, tab_audit, tab_road, tab_cam = st.tabs([
    "Overview", "Map", "Rain vs congestion", "Traffic DNA",
    "Vulnerability & Corridors", "Anomalies & CCTV Audit", "Road context", "Camera explorer",
])

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
    map_choices = ["Average traffic", "Rain effect", "Peak hour", "Weekend share"]
    if has_dna:
        map_choices.append("Traffic DNA archetype")
    metric = st.radio("Colour cameras by", map_choices, horizontal=True)
    sel = f.groupby("camera_id").agg(traffic=("n_calibrated", "mean"), snaps=("n_calibrated", "size")).reset_index()
    e = f.groupby(["camera_id", "wet"])["excess_calibrated"].agg(["mean", "size"]).unstack()
    rain_eff = (100 * (np.expm1(e[("mean", True)]) - np.expm1(e[("mean", False)])))
    rain_eff = rain_eff.where((e[("size", True)] >= 10) & (e[("size", False)] >= 10)).rename("rain_effect")
    m = cams.merge(sel, on="camera_id").merge(rain_eff.reset_index(), on="camera_id", how="left")
    color = {
        "Average traffic": "traffic",
        "Rain effect": "rain_effect",
        "Peak hour": "peak_hour",
        "Weekend share": "weekend_kept_pct",
        "Traffic DNA archetype": "archetype",
    }[metric]
    hover = {c: True for c in ["archetype", "road_class", "lanes", "n_traffic_signals_100m", "n_bus_stop_500m",
                               "n_rail_station_500m", "n_mall_market_500m", "peak_hour"]
             if c in m.columns}
    if "weekend_kept_pct" in m.columns:
        hover["weekend_kept_pct"] = ":.0f"

    map_kwargs = dict(
        lat="latitude", lon="longitude", color=color, size="traffic", size_max=18, zoom=11, height=600,
        center={"lat": float(m["latitude"].mean()), "lon": float(m["longitude"].mean())},
        hover_name="name", hover_data={"traffic": ":.1f", "rain_effect": ":+.1f", **hover},
        map_style="open-street-map",
        labels={"weekend_kept_pct": "weekend % of weekday", "rain_effect": "rain effect (pts)",
                "n_traffic_signals_100m": "signals within 100 m", "n_bus_stop_500m": "bus stops within 500 m",
                "n_mall_market_500m": "malls within 500 m", "archetype": "Traffic DNA"},
    )
    if color == "archetype":
        map_kwargs["color_discrete_map"] = ARCH_COLORS
    else:
        map_kwargs["color_continuous_scale"] = {"rain_effect": "RdBu_r", "weekend_kept_pct": "RdYlBu"}.get(color, "YlOrRd")
        if color == "rain_effect":
            map_kwargs["color_continuous_midpoint"] = 0
        elif color == "weekend_kept_pct":
            map_kwargs["range_color"] = (40, 100)

    fig = px.scatter_map(m, **map_kwargs)
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig, width="stretch")
    st.caption("Rain effect = calibrated traffic vs the camera's usual for that hour, wet hours minus dry hours "
               "(percentage points). Cameras with fewer than 10 wet or dry snapshots in the selection are blank. "
               "Weekend share = weekend traffic as % of weekday traffic at the same hours (whole week, not filtered); "
               "office areas empty out at weekends, shopping and old-town areas stay busy.")
    table_cols = ["name"] + [c for c in ["archetype"] if c in m.columns] + [
        "traffic", "rain_effect", "peak_hour"] + [c for c in ["road_class", "lanes", "n_traffic_signals_100m"] if c in m.columns]
    st.dataframe(m.sort_values("traffic", ascending=False)[table_cols].head(15).round(1), hide_index=True, width="stretch")

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

# ---- Traffic DNA ----
with tab_dna:
    if not dna_tables or "archetype" not in cams.columns:
        st.warning("Run `uv run python -m cctv.dna` then `uv run python -m cctv.mart` to generate Traffic DNA clusters.")
    else:
        sel_df, profs_df, sig_df, hourly_df = (
            dna_tables["sel"], dna_tables["profs"], dna_tables["sig"], dna_tables["hourly"]
        )
        r2_row = sig_df[sig_df["feature"] == "cluster_r2"].iloc[0]
        sil_row = sig_df[sig_df["feature"] == "cluster_silhouette"].iloc[0]
        k_chosen = int(len(profs_df))
        ari_val = float(sel_df.loc[sel_df["k"] == k_chosen, "boot_ari"].iloc[0])

        k_cols = st.columns(4)
        k_cols[0].metric("Archetypes (K-Means++)", f"k = {k_chosen}", help="Zoom-invariant 06:00–20:00 temporal shape features.")
        k_cols[1].metric("Variance explained (R²)", f"{r2_row['statistic']:.3f}",
                         delta=f"perm p = {r2_row['p_value']:.4f}", delta_color="off")
        k_cols[2].metric("Mean silhouette", f"{sil_row['statistic']:.3f}",
                         delta=f"perm p = {sil_row['p_value']:.4f}", delta_color="off")
        k_cols[3].metric("Bootstrap ARI stability", f"{ari_val:.3f}", help="85% camera subsampling agreement over 50 runs.")

        c1, c2 = st.columns([1.25, 1.0])
        fig_rhythm = go.Figure()
        for row in profs_df.sort_values("cluster_id").itertuples():
            arch = row.archetype
            col = ARCH_COLORS.get(arch, "#555")
            sub = hourly_df[hourly_df["cluster_id"] == int(row.cluster_id)]
            wd = sub[sub["daytype"] == "weekday"].sort_values("hour")
            we = sub[sub["daytype"] == "weekend"].sort_values("hour")
            fig_rhythm.add_scatter(x=wd["hour"], y=wd["rel_traffic"], mode="lines+markers",
                                   name=f"{arch} · weekday (n={int(row.n_cameras)})",
                                   line=dict(color=col, width=2.5))
            fig_rhythm.add_scatter(x=we["hour"], y=we["rel_traffic"], mode="lines",
                                   name=f"{arch} · weekend",
                                   line=dict(color=col, width=1.8, dash="dash"))
        fig_rhythm.add_hline(y=1.0, line_dash="dot", line_color="#888")
        fig_rhythm.update_layout(
            title="Traffic DNA rhythms: weekday (solid) vs weekend (dashed)",
            xaxis_title="Hour of day", yaxis_title="Traffic / camera weekday mean", height=420,
            legend=dict(orientation="h", y=-0.25),
        )
        c1.plotly_chart(fig_rhythm, width="stretch")

        pca_cams = cams.dropna(subset=["pca1", "pca2", "archetype"])
        fig_pca = px.scatter(
            pca_cams, x="pca1", y="pca2", color="archetype", size="mean_calibrated",
            hover_name="name",
            hover_data={"road_class": True, "weekend_kept_pct": ":.0f", "n_mall_market_500m": True,
                        "n_hospital_500m": True, "pca1": ":.2f", "pca2": ":.2f"},
            color_discrete_map=ARCH_COLORS, title="2D PCA of 6 Traffic DNA features (100 cameras)",
            labels={"pca1": "PC 1", "pca2": "PC 2", "archetype": "Archetype"}, height=420,
        )
        fig_pca.update_layout(legend=dict(orientation="h", y=-0.25))
        c2.plotly_chart(fig_pca, width="stretch")

        c3, c4 = st.columns([0.9, 1.35])
        fig_k = make_subplots(specs=[[{"secondary_y": True}]])
        fig_k.add_scatter(x=sel_df["k"], y=sel_df["silhouette"], mode="lines+markers", name="Silhouette",
                          line=dict(color="#2a78d6", width=2.2), secondary_y=False)
        fig_k.add_scatter(x=sel_df["k"], y=sel_df["boot_ari"], mode="lines+markers", name="Bootstrap ARI",
                          line=dict(color="#eb6834", width=2.2, dash="dot"), secondary_y=True)
        fig_k.update_layout(title="Cluster k selection (k=3 maximizes ARI stability)", xaxis_title="k",
                            height=340, legend=dict(orientation="h", y=-0.22))
        fig_k.update_yaxes(title_text="Silhouette", secondary_y=False)
        fig_k.update_yaxes(title_text="Bootstrap ARI", secondary_y=True, showgrid=False)
        c3.plotly_chart(fig_k, width="stretch")

        c4.subheader("External Statistical Validation (Held-Out Features)")
        disp_sig = sig_df[sig_df["test_type"].isin(["external_kw", "hypothesis_check"])][
            ["feature", "statistic", "p_value", "fdr_q", "p_allday_vs_morning",
             "mean_all_day", "mean_evening", "mean_morning"]
        ].sort_values("p_value")
        c4.dataframe(disp_sig.round(4), hide_index=True, width="stretch", height=300)

# ---- Vulnerability & Corridors (Ideas 4, 2, 6) ----
with tab_vuln:
    if not ins_tables:
        st.warning("Run `uv run python -m cctv.insights` to populate rain vulnerability, corridor links, and tidal pairs.")
    else:
        vuln_df = ins_tables["vuln"]
        tidal_pairs = ins_tables["tidal_pairs"]
        tidal_hourly = ins_tables["tidal_hourly"]
        decay_df = ins_tables["decay"]
        spatial_tests = ins_tables["spatial_tests"].set_index("test_name")
        links_df = ins_tables["links"]

        st.subheader("1. Where Heavy Rain Hits Hardest (Idea 4 · Zoom-Free DiD)")
        inter = vuln_df[vuln_df["row_type"] == "interaction"].copy()
        fig_v = go.Figure()
        for row in inter.iloc[::-1].itertuples():
            fig_v.add_scatter(
                x=[row.pts_b, row.pts_a], y=[row.group_b, row.group_a],
                mode="markers", marker=dict(size=10, color=["#8a8984", WET]),
                error_x=dict(
                    type="data", symmetric=False,
                    array=[row.hi_b - row.pts_b, row.hi_a - row.pts_a],
                    arrayminus=[row.pts_b - row.lo_b, row.pts_a - row.lo_a],
                ),
                showlegend=False,
            )
        fig_v.add_vline(x=0, line_dash="dash", line_color="#666")
        fig_v.update_layout(
            title="Heavy rain (>5 mm/h) minus dry by OSM infrastructure (95% camera-day CI)",
            xaxis_title="Percentage points vs dry hours", height=360,
        )
        c_v1, c_v2 = st.columns([1.2, 1.0])
        c_v1.plotly_chart(fig_v, width="stretch")
        c_v2.dataframe(
            inter[["factor", "group_a", "pts_a", "group_b", "pts_b", "did_pts", "did_lo", "did_hi", "boot_p"]].round(3),
            hide_index=True, width="stretch", height=320,
        )

        st.divider()
        st.subheader("2. Spatial Corridor Synchronization (Idea 2 · Local Residuals)")
        m_nf = spatial_tests.loc["mantel_near_vs_far"]
        m_dec = spatial_tests.loc["mantel_dist_decay_r"]
        sig_links = links_df[links_df["fdr_q"] < 0.05]
        sk = st.columns(4)
        sk[0].metric("Mantel near (<=1km) vs far", f"{m_nf['observed']:+.4f}", delta=f"p = {m_nf['p_value']:.4f}", delta_color="off")
        sk[1].metric("Mantel log-distance r", f"{m_dec['observed']:+.3f}", delta=f"p = {m_dec['p_value']:.4f}", delta_color="off")
        sk[2].metric("Significant corridor links (q<0.05)", f"{len(sig_links)} / {len(links_df)}")
        sk[3].metric("NN info", "Lag-0h sync", help=str(spatial_tests.loc["nn_sync_summary", "detail"]))

        c_s1, c_s2 = st.columns([1.0, 1.2])
        fig_dec = go.Figure()
        fig_dec.add_scatter(x=decay_df["band"], y=decay_df["mean_raw_r"], mode="lines+markers", name="Raw hourly excess")
        fig_dec.add_scatter(x=decay_df["band"], y=decay_df["mean_local_r"], mode="lines+markers", name="Local residual (citywide removed)")
        fig_dec.add_hline(y=0, line_dash="dot", line_color="#888")
        fig_dec.update_layout(title="Distance decay of hourly correlation", xaxis_title="Distance band", yaxis_title="Mean r", height=380)
        c_s1.plotly_chart(fig_dec, width="stretch")

        top_links = links_df.head(30)
        edge_lats, edge_lons = [], []
        for row in top_links.itertuples():
            edge_lats.extend([row.lat_a, row.lat_b, None])
            edge_lons.extend([row.lon_a, row.lon_b, None])
        fig_net = go.Figure()
        fig_net.add_trace(go.Scattermap(
            lat=edge_lats, lon=edge_lons, mode="lines",
            line=dict(width=3, color="#2a78d6"), name="Top synchronized links (<=2 km)",
        ))
        fig_net.add_trace(go.Scattermap(
            lat=cams["latitude"], lon=cams["longitude"], mode="markers",
            marker=dict(size=7, color="#333"), text=cams["name"], name="Cameras",
        ))
        fig_net.update_layout(
            map=dict(style="open-street-map", center=dict(lat=float(cams["latitude"].mean()), lon=float(cams["longitude"].mean())), zoom=11),
            margin=dict(l=0, r=0, t=30, b=0), height=380, title="Top 30 locally synchronized camera pairs (<=2 km)",
        )
        c_s2.plotly_chart(fig_net, width="stretch")
        st.dataframe(
            links_df[["cam_a", "cam_b", "name_a", "name_b", "dist_km", "local_r", "lag1_r", "p_value", "fdr_q"]].head(15).round(4),
            hide_index=True, width="stretch",
        )

        st.divider()
        st.subheader("3. Directional Tidal Flow Asymmetry (Idea 6 · 21 Co-Located Pairs <=100m)")
        c_t1, c_t2 = st.columns([1.0, 1.15])
        pair_pick = c_t1.selectbox(
            "Inspect co-located camera pair",
            tidal_pairs["pair_id"].tolist(),
            format_func=lambda pid: (
                f"{pid} ({tidal_pairs.set_index('pair_id').at[pid, 'dist_m']}m, "
                f"swing={tidal_pairs.set_index('pair_id').at[pid, 'tidal_swing']:.2f}, "
                f"q={tidal_pairs.set_index('pair_id').at[pid, 'fdr_q']:.3f}) · "
                f"{tidal_pairs.set_index('pair_id').at[pid, 'name_a'][:36]}"
            ),
        )
        prow = tidal_pairs.set_index("pair_id").loc[pair_pick]
        c_t1.caption(f"Cam {int(prow['cam_a'])}: {prow['dir_a']}  |  Cam {int(prow['cam_b'])}: {prow['dir_b']}")
        sub_h = tidal_hourly[tidal_hourly["pair_id"] == pair_pick].sort_values("hour")
        fig_tidal = make_subplots(specs=[[{"secondary_y": True}]])
        fig_tidal.add_scatter(x=sub_h["hour"], y=sub_h["norm_a"], mode="lines+markers", name=f"Cam {int(prow['cam_a'])} (norm)")
        fig_tidal.add_scatter(x=sub_h["hour"], y=sub_h["norm_b"], mode="lines+markers", name=f"Cam {int(prow['cam_b'])} (norm)")
        fig_tidal.add_bar(x=sub_h["hour"], y=sub_h["asymmetry"], name="Asymmetry (A-B)/(A+B)", opacity=0.35, secondary_y=True)
        fig_tidal.update_layout(title=f"Hourly directional balance: pair {pair_pick}", height=360, legend=dict(orientation="h", y=-0.22))
        fig_tidal.update_yaxes(title_text="Normalized weekday traffic", secondary_y=False)
        fig_tidal.update_yaxes(title_text="Asymmetry", secondary_y=True, showgrid=False)
        c_t1.plotly_chart(fig_tidal, width="stretch")
        c_t2.dataframe(
            tidal_pairs[["pair_id", "dist_m", "am_asym", "pm_asym", "tidal_swing", "reverses_sign",
                         "weekdays_reversing", "p_value", "fdr_q", "name_a"]].round(4),
            hide_index=True, width="stretch", height=410,
        )

# ---- Anomalies & CCTV Audit (Idea 7) ----
with tab_audit:
    if not audit_tables:
        st.warning("Run `uv run python -m cctv.audit --stage frames` and `--stage shocks` to inspect CCTV health and anomalies.")
    else:
        health_df = audit_tables["health"]
        outages_df = audit_tables["outages"]
        tot_frames = int(health_df["total_frames"].sum())
        tot_blank = int(health_df["blank_frames"].sum())
        tot_white = int(health_df["whiteout_frames"].sum())
        tot_frozen = int(health_df["visual_frozen_frames"].sum())
        tot_usable = int(health_df["usable_frames"].sum())

        ak = st.columns(4)
        ak[0].metric("Raw frames audited", f"{tot_frames:,}")
        ak[1].metric("Blank / whiteout outages", f"{tot_blank:,}", delta=f"{tot_white:,} pure-white (bright>=250)", delta_color="off")
        ak[2].metric("Watermark-frozen feeds", f"{tot_frozen:,}", help="Detected via center-crop pixel MAD < 1.0 despite live clock watermark.")
        ak[3].metric("Usable live frames", f"{tot_usable:,}", delta=f"{100 * tot_usable / tot_frames:.1f}%", delta_color="off")

        ca1, ca2 = st.columns([1.1, 1.0])
        hr_out = outages_df.groupby("hour")[["blank_frames", "visual_frozen_frames"]].sum().reset_index()
        fig_out = px.bar(
            hr_out, x="hour", y=["blank_frames", "visual_frozen_frames"], barmode="group",
            title="Daily CCTV outages by hour (07:00 AM whiteouts vs frozen feeds)",
            labels={"value": "Bad frames (7 days)", "hour": "Hour of day", "variable": "Issue"},
        )
        ca1.plotly_chart(fig_out, width="stretch")

        if "daily_eve" in audit_tables:
            de_df = audit_tables["daily_eve"].copy()
            de_df["condition"] = de_df["wet"].map({True: "Wet (>0.1 mm/h)", False: "Dry"})
            fig_eve = px.bar(
                de_df, x="date_str", y="pct_vs_usual", color="condition", barmode="group",
                color_discrete_map={"Dry": DRY, "Wet (>0.1 mm/h)": WET},
                title="Evening (>=17:00) % vs usual by day (Mon 31 Aug is 100% wet & −17%)",
                labels={"date_str": "Date", "pct_vs_usual": "% vs usual"},
            )
            ca2.plotly_chart(fig_eve, width="stretch")

        ca3, ca4 = st.columns([0.9, 1.3])
        ca3.subheader("Most Degraded Cameras")
        h_named = health_df.merge(cams[["camera_id", "name"]], on="camera_id", how="left")
        ca3.dataframe(
            h_named[["camera_id", "name", "blank_frames", "visual_frozen_frames", "bad_pct"]].head(15).round(1),
            hide_index=True, width="stretch", height=320,
        )

        if "shocks" in audit_tables:
            shocks_df = audit_tables["shocks"]
            ca4.subheader("Traffic Shock Explorer (|z| >= 2.5)")
            s_types = sorted(shocks_df["shock_type"].unique())
            pick_types = ca4.multiselect("Shock type", s_types, default=s_types)
            sub_sh = shocks_df[shocks_df["shock_type"].isin(pick_types)].reset_index(drop=True)
            ca4.dataframe(
                sub_sh[["camera_id", "name", "date_str", "hour", "shock_type", "z_score", "pct_vs_usual", "rain_mean", "cal_mean"]].head(30).round(2),
                hide_index=True, width="stretch", height=250,
            )
            if len(sub_sh) and RAW.exists():
                idx_sh = st.selectbox(
                    "Inspect raw snapshot for detected shock",
                    list(range(min(50, len(sub_sh)))),
                    format_func=lambda i: (
                        f"{sub_sh.at[i, 'date_str']} {int(sub_sh.at[i, 'hour']):02d}:00 · "
                        f"Cam {int(sub_sh.at[i, 'camera_id'])} ({sub_sh.at[i, 'shock_type']}, z={sub_sh.at[i, 'z_score']:+.2f})"
                    ),
                )
                srow = sub_sh.iloc[idx_sh]
                img_path = RAW / str(srow["rep_path"])
                sc1, sc2 = st.columns([1.6, 1.0])
                if img_path.exists():
                    sc1.image(str(img_path), width="stretch")
                sc2.write({
                    "camera": f"{int(srow['camera_id'])} · {srow['name']}",
                    "date_hour": f"{srow['date_str']} {int(srow['hour']):02d}:00",
                    "shock_type": str(srow["shock_type"]),
                    "z_score": round(float(srow["z_score"]), 2),
                    "neighbor_z": round(float(srow["neighbor_z"]), 2) if pd.notna(srow["neighbor_z"]) else None,
                    "citywide_z": round(float(srow["citywide_z"]), 2),
                    "pct_vs_usual": f"{srow['pct_vs_usual']:+.1f}%",
                    "mean_calibrated": round(float(srow["cal_mean"]), 1),
                    "mean_rain_mm": round(float(srow["rain_mean"]), 2),
                })

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
        poi_candidates = [
            ("n_traffic_signals_100m", "traffic signals (within 100 m)"),
            ("n_traffic_signals_500m", "traffic signals (within 500 m)"),
            ("n_bus_stop_500m", "bus stops (within 500 m)"),
            ("n_rail_station_500m", "rail stations (within 500 m)"),
            ("n_school_500m", "schools (within 500 m)"),
            ("n_mall_market_500m", "malls / markets (within 500 m)"),
            ("n_hospital_500m", "hospitals (within 500 m)"),
        ]
        avail_pois = {col: label for col, label in poi_candidates if col in r.columns}
        poi = st.selectbox("Nearby places / infrastructure (OpenStreetMap)", list(avail_pois), format_func=avail_pois.get)
        st.plotly_chart(px.strip(r, x=poi, y="traffic", hover_name="name", color="road_class",
                                 category_orders={"road_class": order},
                                 title=f"Traffic vs {avail_pois[poi]}",
                                 labels={"traffic": "Vehicles per frame", poi: avail_pois[poi]}),
                        width="stretch")

# ---- Camera explorer ----
with tab_cam:
    options = cams.sort_values("name")
    cam_id = st.selectbox("Camera", options["camera_id"],
                          format_func=lambda c: f"{c} · {options.set_index('camera_id').at[c, 'name']}")
    info = cams.set_index("camera_id").loc[cam_id]
    cs = f[f["camera_id"] == cam_id].sort_values("timestamp")
    k = st.columns(5)
    k[0].metric("Avg vehicles", f"{cs['n_calibrated'].mean():.1f}" if len(cs) else "–")
    k[1].metric("Peak hour", f"{int(info['peak_hour'])}:00")
    lanes_str = f" ({int(info['lanes'])}L)" if "lanes" in info and pd.notna(info["lanes"]) else ""
    k[2].metric("Road", f"{info.get('road_class', '–')}{lanes_str}" if has_osm else "–")
    k[3].metric("Traffic DNA", str(info.get("archetype", "–")) if has_dna else "–")
    k[4].metric("Rain effect (all data)", f"{info['rain_effect_pct']:+.1f} pts" if pd.notna(info["rain_effect_pct"]) else "–")

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
        c2.write({
            "time": row["timestamp"].strftime("%a %d %b %H:%M"),
            "light": row["light"],
            "rain mm/h": round(float(row["rain_now"]), 1),
            "vehicles (raw)": int(row["n_vehicles"]),
            "vehicles (calibrated)": round(float(row["n_calibrated"]), 1),
            "cars": int(row["n_car"]),
            "motorcycles": int(row["n_motorcycle"]),
            "trucks": int(row["n_truck"]),
            "buses": int(row["n_bus"]),
        })
