"""Step 8b: statistical insight modules for Ideas 4, 6, and 2.

Computes three zoom-invariant analyses on cleaned CCTV snapshots and OpenStreetMap context:
  1. Rain vulnerability interactions (Idea 4): camera-day cluster bootstrap DiD across
     signalized intersections, bridges vs. surface roads, rail transit access, road class,
     and Traffic DNA archetypes.
  2. Directional tidal flow asymmetry (Idea 6): AM vs. PM reversal across co-located
     opposite-direction camera pairs (<=100 m) with permutation p-values and FDR.
  3. Spatial corridor synchronization (Idea 2): distance-decay of local hourly residuals
     with Mantel node-permutation tests and day-block-permuted corridor links.

Writes data/processed/insights/:
  rain_vulnerability.csv
  tidal_pairs.csv
  tidal_hourly.parquet
  distance_decay.csv
  spatial_tests.csv
  corridor_links.csv

    uv run python -m cctv.insights
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from cctv.dna import benjamini_hochberg, pairwise_diff_perm


def _cam_names(info: pd.DataFrame) -> pd.Series:
    df = info.copy()
    df["camera_id"] = df["camera_id"].astype(int)
    df["name"] = np.where(
        df["location_en"].str.contains("connect BMAcctv", na=True),
        df["location"],
        df["location_en"],
    )
    return df.set_index("camera_id")["name"]


def _xy_metres(info: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    lat0 = float(info["latitude"].mean())
    x = info["longitude"].to_numpy(float) * 111_320.0 * np.cos(np.radians(lat0))
    y = info["latitude"].to_numpy(float) * 111_320.0
    return x, y


def _cluster_boot_heavy_vs_dry(df: pd.DataFrame, n_boot: int = 2000, seed: int = 403) -> tuple[float, float, float, int, int]:
    """Camera-day cluster bootstrap for heavy (>5 mm/h) minus dry excess_calibrated."""
    heavy = df["rain_now"] > 5
    dry = ~df["wet"]
    cl = df["camera_id"].astype(str) + "_" + df["timestamp"].dt.date.astype(str)
    all_cl = cl.unique()
    h_sum = df.loc[heavy].groupby(cl)["excess_calibrated"].sum().reindex(all_cl, fill_value=0.0).to_numpy()
    h_n = df.loc[heavy].groupby(cl).size().reindex(all_cl, fill_value=0).to_numpy()
    d_sum = df.loc[dry].groupby(cl)["excess_calibrated"].sum().reindex(all_cl, fill_value=0.0).to_numpy()
    d_n = df.loc[dry].groupby(cl).size().reindex(all_cl, fill_value=0).to_numpy()
    if h_n.sum() == 0 or d_n.sum() == 0:
        return float("nan"), float("nan"), float("nan"), int(h_n.sum()), int(df["camera_id"].nunique())
    pt = float(100.0 * (np.expm1(h_sum.sum() / h_n.sum()) - np.expm1(d_sum.sum() / d_n.sum())))
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(all_cl), size=len(all_cl))
        hn, dn = h_n[idx].sum(), d_n[idx].sum()
        if hn > 0 and dn > 0:
            draws.append(100.0 * (np.expm1(h_sum[idx].sum() / hn) - np.expm1(d_sum[idx].sum() / dn)))
    arr = np.array(draws)
    return pt, float(np.quantile(arr, 0.025)), float(np.quantile(arr, 0.975)), int(h_n.sum()), int(df["camera_id"].nunique())


def compute_rain_vulnerability(
    snaps: pd.DataFrame, osm: pd.DataFrame, dna: pd.DataFrame | None = None, n_boot: int = 2000, seed: int = 403
) -> pd.DataFrame:
    """Camera-day cluster bootstrap DiD of heavy rain (>5 mm/h) across OSM infrastructure splits."""
    df = snaps.copy()
    df["camera_id"] = df["camera_id"].astype(int)
    osm_c = osm.copy()
    osm_c["camera_id"] = osm_c["camera_id"].astype(int)
    df = df.merge(
        osm_c[["camera_id", "n_traffic_signals_100m", "is_bridge", "n_rail_station_500m", "road_class"]],
        on="camera_id", how="left", suffixes=("", "_osm"),
    )
    if "road_class_osm" in df.columns:
        df["road_class"] = df["road_class"].fillna(df["road_class_osm"])

    df["signalized_100m"] = df["n_traffic_signals_100m"].fillna(0) > 0
    df["surface_vs_bridge"] = ~df["is_bridge"].fillna(False).astype(bool)
    df["transit_desert"] = df["n_rail_station_500m"].fillna(0) == 0
    df["primary_plus"] = df["road_class"].isin(["motorway", "trunk", "primary"])

    splits = [
        ("signalized_100m", "Signalized (<=100m)", "Mid-block"),
        ("surface_vs_bridge", "Surface road", "Bridge / viaduct"),
        ("transit_desert", "No BTS/MRT (500m)", "Near BTS/MRT (<=500m)"),
        ("primary_plus", "Primary / motorway / trunk", "Secondary / tertiary"),
    ]

    cl = df["camera_id"].astype(str) + "_" + df["timestamp"].dt.date.astype(str)
    all_cl = cl.unique()
    df["heavy"] = df["rain_now"] > 5
    df["dry"] = ~df["wet"]
    rng = np.random.default_rng(seed)

    rows = []
    for col, label_a, label_b in splits:
        stats = {}
        for val in (True, False):
            sub = df[df[col] == val]
            stats[val] = (
                sub.loc[sub["heavy"]].groupby(cl[df[col] == val])["excess_calibrated"].sum().reindex(all_cl, fill_value=0.0).to_numpy(),
                sub.loc[sub["heavy"]].groupby(cl[df[col] == val]).size().reindex(all_cl, fill_value=0).to_numpy(),
                sub.loc[sub["dry"]].groupby(cl[df[col] == val])["excess_calibrated"].sum().reindex(all_cl, fill_value=0.0).to_numpy(),
                sub.loc[sub["dry"]].groupby(cl[df[col] == val]).size().reindex(all_cl, fill_value=0).to_numpy(),
                int(sub.loc[sub["heavy"]].shape[0]),
                int(sub["camera_id"].nunique()),
            )

        def _eval(idx: np.ndarray | None = None):
            out = {}
            for val in (True, False):
                hs, hn, ds_, dn, _, _ = stats[val]
                if idx is not None:
                    hs, hn, ds_, dn = hs[idx], hn[idx], ds_[idx], dn[idx]
                if hn.sum() == 0 or dn.sum() == 0:
                    return None
                out[val] = 100.0 * (np.expm1(hs.sum() / hn.sum()) - np.expm1(ds_.sum() / dn.sum()))
            return out[True], out[False], out[True] - out[False]

        pt_a, pt_b, did_pt = _eval()
        draws = [r for _ in range(n_boot) if (r := _eval(rng.integers(0, len(all_cl), len(all_cl)))) is not None]
        arr = np.array(draws)
        lo_a, hi_a = np.quantile(arr[:, 0], [0.025, 0.975])
        lo_b, hi_b = np.quantile(arr[:, 1], [0.025, 0.975])
        did_lo, did_hi = np.quantile(arr[:, 2], [0.025, 0.975])
        n_le0, n_ge0 = int((arr[:, 2] <= 0).sum()), int((arr[:, 2] >= 0).sum())
        boot_p = float(min(1.0, (2 * min(n_le0, n_ge0) + 1) / (len(arr) + 1)))
        rows.append({
            "row_type": "interaction",
            "factor": col,
            "group_a": label_a,
            "pts_a": pt_a, "lo_a": float(lo_a), "hi_a": float(hi_a),
            "n_heavy_a": stats[True][4], "n_cams_a": stats[True][5],
            "group_b": label_b,
            "pts_b": pt_b, "lo_b": float(lo_b), "hi_b": float(hi_b),
            "n_heavy_b": stats[False][4], "n_cams_b": stats[False][5],
            "did_pts": did_pt, "did_lo": float(did_lo), "did_hi": float(did_hi), "boot_p": boot_p,
        })

    if dna is not None and "archetype" in dna.columns:
        dna_c = dna[["camera_id", "archetype"]].copy()
        dna_c["camera_id"] = dna_c["camera_id"].astype(int)
        df_d = df.merge(dna_c, on="camera_id", how="left", suffixes=("", "_dna"))
        if "archetype_dna" in df_d.columns:
            df_d["archetype"] = df_d["archetype"].fillna(df_d["archetype_dna"])
        for arch, grp in df_d.groupby("archetype"):
            pt, lo, hi, nh, nc = _cluster_boot_heavy_vs_dry(grp, n_boot=n_boot, seed=seed)
            rows.append({
                "row_type": "archetype",
                "factor": "traffic_dna",
                "group_a": str(arch),
                "pts_a": pt, "lo_a": lo, "hi_a": hi, "n_heavy_a": nh, "n_cams_a": nc,
                "group_b": "dry baseline",
                "pts_b": 0.0, "lo_b": float("nan"), "hi_b": float("nan"),
                "n_heavy_b": int((~grp["wet"]).sum()), "n_cams_b": nc,
                "did_pts": pt, "did_lo": lo, "did_hi": hi, "boot_p": float("nan"),
            })

    return pd.DataFrame(rows)


def compute_tidal_flow(
    snaps: pd.DataFrame, info: pd.DataFrame, max_dist_m: float = 100.0, n_perm: int = 5000, seed: int = 403
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Measure AM vs. PM directional asymmetry across co-located camera pairs (<= max_dist_m)."""
    cams = info.copy()
    cams["camera_id"] = cams["camera_id"].astype(int)
    cams["name"] = _cam_names(info).reindex(cams["camera_id"]).to_numpy()
    cams = cams.set_index("camera_id")
    cam_ids = cams.index.to_numpy()
    x, y = _xy_metres(cams)
    dist_m = np.sqrt((x[:, None] - x[None, :]) ** 2 + (y[:, None] - y[None, :]) ** 2)

    df = snaps.copy()
    df["camera_id"] = df["camera_id"].astype(int)
    df["date_str"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    wd = df[(df["daytype"] == "weekday") & (df["hour"].between(6, 20))].copy()
    piv = wd.groupby(["camera_id", "hour"])["n_calibrated"].mean().unstack().reindex(columns=range(6, 21))
    piv = piv.interpolate(axis=1, limit_direction="both")
    wd_mean = piv.mean(axis=1)
    norm_piv = piv.div(wd_mean, axis=0)

    wd["norm"] = wd["n_calibrated"] / wd["camera_id"].map(wd_mean)
    slot_norm = wd.groupby(["camera_id", "date_str", "hour"])["norm"].mean().unstack("camera_id")

    pair_rows = []
    hourly_rows = []
    for i in range(len(cam_ids)):
        for j in range(i + 1, len(cam_ids)):
            if dist_m[i, j] > max_dist_m:
                continue
            a, b = int(cam_ids[i]), int(cam_ids[j])
            if a not in norm_piv.index or b not in norm_piv.index:
                continue
            na = norm_piv.loc[a].to_numpy(float)
            nb = norm_piv.loc[b].to_numpy(float)
            asym_h = (na - nb) / np.maximum(na + nb, 1e-9)
            pair_id = f"{a}-{b}"
            for idx_h, hr in enumerate(range(6, 21)):
                hourly_rows.append({
                    "pair_id": pair_id, "cam_a": a, "cam_b": b, "hour": hr,
                    "norm_a": float(na[idx_h]), "norm_b": float(nb[idx_h]), "asymmetry": float(asym_h[idx_h]),
                })

            am_asym = float(np.mean(asym_h[0:4]))   # hours 6, 7, 8, 9
            pm_asym = float(np.mean(asym_h[10:14]))  # hours 16, 17, 18, 19
            swing = float(abs(am_asym - pm_asym))
            rev = bool(am_asym * pm_asym < 0)

            sa, sb = slot_norm[a], slot_norm[b]
            valid = sa.notna() & sb.notna()
            s_asym = ((sa[valid] - sb[valid]) / np.maximum(sa[valid] + sb[valid], 1e-9)).reset_index(name="asym")
            am_vals = s_asym.loc[s_asym["hour"].isin([6, 7, 8, 9]), "asym"].to_numpy()
            pm_vals = s_asym.loc[s_asym["hour"].isin([16, 17, 18, 19]), "asym"].to_numpy()
            _, p_val = pairwise_diff_perm(am_vals, pm_vals, n_perm=n_perm, seed=seed)

            day_am = s_asym[s_asym["hour"].isin([6, 7, 8, 9])].groupby("date_str")["asym"].mean()
            day_pm = s_asym[s_asym["hour"].isin([16, 17, 18, 19])].groupby("date_str")["asym"].mean()
            common_days = day_am.index.intersection(day_pm.index)
            expected_sign = np.sign(am_asym - pm_asym)
            weekdays_rev = int(sum(
                (day_am[d] * day_pm[d] < 0) and (np.sign(day_am[d] - day_pm[d]) == expected_sign)
                for d in common_days
            ))

            pair_rows.append({
                "pair_id": pair_id,
                "cam_a": a,
                "cam_b": b,
                "name_a": str(cams.at[a, "name"]),
                "name_b": str(cams.at[b, "name"]),
                "dir_a": str(cams.at[a, "location_detail_en"]) if "location_detail_en" in cams.columns else "",
                "dir_b": str(cams.at[b, "location_detail_en"]) if "location_detail_en" in cams.columns else "",
                "dist_m": round(float(dist_m[i, j]), 1),
                "am_asym": am_asym,
                "pm_asym": pm_asym,
                "tidal_swing": swing,
                "reverses_sign": rev,
                "weekdays_reversing": weekdays_rev,
                "n_weekdays": int(len(common_days)),
                "p_value": p_val,
            })

    pairs_df = pd.DataFrame(pair_rows)
    if not pairs_df.empty:
        pairs_df["fdr_q"] = benjamini_hochberg(pairs_df["p_value"].to_numpy())
        pairs_df = pairs_df.sort_values("tidal_swing", ascending=False).reset_index(drop=True)
    hourly_df = pd.DataFrame(hourly_rows)
    return pairs_df, hourly_df


def _day_block_perm_corr(
    mat_a: np.ndarray, mat_b: np.ndarray, obs_r: float, n_perm: int, rng: np.random.Generator
) -> float:
    """Day-block permutation p-value preserving within-day hourly autocorrelation."""
    n_days = mat_a.shape[0]
    if n_days < 3 or np.isnan(obs_r):
        return 1.0
    ge = 0
    for _ in range(n_perm):
        perm = rng.permutation(n_days)
        bp = mat_b[perm]
        valid = (~np.isnan(mat_a)) & (~np.isnan(bp))
        if valid.sum() < 20:
            continue
        va = mat_a[valid]
        vb = bp[valid]
        va_c = va - va.mean()
        vb_c = vb - vb.mean()
        denom = float(np.sqrt((va_c ** 2).sum() * (vb_c ** 2).sum()))
        r_p = float((va_c * vb_c).sum() / denom) if denom > 0 else 0.0
        if abs(r_p) >= abs(obs_r) - 1e-12:
            ge += 1
    return float((ge + 1) / (n_perm + 1))


def compute_spatial_sync(
    snaps: pd.DataFrame,
    info: pd.DataFrame,
    max_link_km: float = 2.0,
    n_mantel: int = 2000,
    n_pair_perm: int = 2000,
    seed: int = 403,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Analyze local hourly spatial synchronization, Mantel distance decay, and corridor links."""
    df = snaps.copy()
    df["camera_id"] = df["camera_id"].astype(int)
    df["slot_h"] = df["timestamp"].dt.floor("h")
    hgrid = df.groupby(["slot_h", "camera_id"])["excess_calibrated"].mean().unstack()
    hgrid_local = hgrid.sub(hgrid.mean(axis=1), axis=0)

    # Continuous 1-hour grid so shift(1) never pairs 21:00 with 06:00 next morning
    full_idx = pd.date_range(hgrid_local.index.min(), hgrid_local.index.max(), freq="h")
    hgrid_cont = hgrid_local.reindex(full_idx)
    hgrid_lag1 = hgrid_cont.shift(1)

    cam_ids = hgrid_local.columns.to_numpy(dtype=int)
    cams = info.copy()
    cams["camera_id"] = cams["camera_id"].astype(int)
    cams["name"] = _cam_names(info).reindex(cams["camera_id"]).to_numpy()
    cams = cams.set_index("camera_id").loc[cam_ids]

    x_m, y_m = _xy_metres(cams)
    d_km = np.sqrt((x_m[:, None] - x_m[None, :]) ** 2 + (y_m[:, None] - y_m[None, :]) ** 2) / 1000.0
    corr_raw = hgrid.corr().to_numpy()
    corr_local = hgrid_local.corr().to_numpy()

    iu, ju = np.triu_indices(len(cam_ids), k=1)
    pairs_all = pd.DataFrame({
        "dist_km": d_km[iu, ju],
        "raw_r": corr_raw[iu, ju],
        "local_r": corr_local[iu, ju],
    })
    bands = [0.0, 0.5, 1.0, 2.0, 5.0, 10.0, np.inf]
    labels = ["<0.5km", "0.5-1km", "1-2km", "2-5km", "5-10km", ">10km"]
    pairs_all["band"] = pd.cut(pairs_all["dist_km"], bands, labels=labels)
    distance_decay = (
        pairs_all.groupby("band", observed=False)
        .agg(
            n_pairs=("local_r", "size"),
            mean_raw_r=("raw_r", "mean"),
            median_raw_r=("raw_r", "median"),
            mean_local_r=("local_r", "mean"),
            median_local_r=("local_r", "median"),
        )
        .reset_index()
    )

    # Mantel node-label permutation tests on local hourly correlation matrix
    rng = np.random.default_rng(seed)
    near_mask = d_km[iu, ju] <= 1.0
    far_mask = d_km[iu, ju] > 2.0
    flat_local = corr_local[iu, ju]
    valid_corr = ~np.isnan(flat_local)
    obs_near_far = float(np.nanmean(flat_local[near_mask]) - np.nanmean(flat_local[far_mask]))
    log_dist = np.log(np.maximum(d_km[iu, ju], 0.05))
    ld_c = log_dist[valid_corr] - log_dist[valid_corr].mean()
    fl_c = flat_local[valid_corr] - flat_local[valid_corr].mean()
    obs_decay_r = float((ld_c * fl_c).sum() / np.sqrt((ld_c ** 2).sum() * (fl_c ** 2).sum()))

    null_nf, null_dr = [], []
    n_cam = len(cam_ids)
    for _ in range(n_mantel):
        p = rng.permutation(n_cam)
        cp = corr_local[np.ix_(p, p)][iu, ju]
        null_nf.append(float(np.nanmean(cp[near_mask]) - np.nanmean(cp[far_mask])))
        cp_c = cp[valid_corr] - cp[valid_corr].mean()
        null_dr.append(float((ld_c * cp_c).sum() / np.sqrt((ld_c ** 2).sum() * (cp_c ** 2).sum())))
    nnf, ndr = np.array(null_nf), np.array(null_dr)

    # Nearest-neighbor raw lag-0h, local lag-0h, and local lag-1h summary
    d_no_self = d_km.copy()
    np.fill_diagonal(d_no_self, np.inf)
    nn_raw_0, nn_loc_0, nn_loc_1 = [], [], []
    for i, cid in enumerate(cam_ids):
        j = int(np.argmin(d_no_self[i]))
        if d_no_self[i, j] <= max_link_km:
            nn_raw_0.append(corr_raw[i, j])
            nn_loc_0.append(corr_local[i, j])
            nn_loc_1.append(hgrid_cont[cid].corr(hgrid_lag1[cam_ids[j]]))

    spatial_tests = pd.DataFrame([
        {
            "test_name": "mantel_near_vs_far",
            "observed": obs_near_far,
            "null_mean": float(nnf.mean()),
            "p_value": float((np.sum(nnf >= obs_near_far - 1e-12) + 1) / (n_mantel + 1)),
            "detail": f"near<=1km mean {np.nanmean(flat_local[near_mask]):+.4f} vs far>2km {np.nanmean(flat_local[far_mask]):+.4f}",
        },
        {
            "test_name": "mantel_dist_decay_r",
            "observed": obs_decay_r,
            "null_mean": float(ndr.mean()),
            "p_value": float((np.sum(ndr <= obs_decay_r + 1e-12) + 1) / (n_mantel + 1)),
            "detail": "corr(local_r, log_dist_km)",
        },
        {
            "test_name": "nn_sync_summary",
            "observed": float(np.nanmedian(nn_loc_0)) if nn_loc_0 else float("nan"),
            "null_mean": float(np.nanmedian(nn_loc_1)) if nn_loc_1 else float("nan"),
            "p_value": float("nan"),
            "detail": f"NN<=2km (n={len(nn_loc_0)}): raw lag0 median={np.nanmedian(nn_raw_0):.3f}, local lag0={np.nanmedian(nn_loc_0):.3f}, local lag1h={np.nanmedian(nn_loc_1):.3f}",
        },
    ])

    # Pre-shape each camera's local hourly residual into (n_days x n_hours) for day-block permutation
    dates = hgrid_local.index.date
    hours = hgrid_local.index.hour
    unique_dates = np.unique(dates)
    unique_hours = np.sort(np.unique(hours))
    date_to_i = {d: idx for idx, d in enumerate(unique_dates)}
    hour_to_j = {h: idx for idx, h in enumerate(unique_hours)}
    cam_mats: dict[int, np.ndarray] = {}
    for cid in cam_ids:
        mat = np.full((len(unique_dates), len(unique_hours)), np.nan, dtype=float)
        ser = hgrid_local[cid].dropna()
        for ts, val in ser.items():
            mat[date_to_i[ts.date()], hour_to_j[ts.hour]] = float(val)
        cam_mats[int(cid)] = mat

    link_rows = []
    for idx_k in range(len(iu)):
        i, j = int(iu[idx_k]), int(ju[idx_k])
        if d_km[i, j] > max_link_km:
            continue
        a, b = int(cam_ids[i]), int(cam_ids[j])
        overlap = int((hgrid_local[a].notna() & hgrid_local[b].notna()).sum())
        if overlap < 40:
            continue
        loc_r = float(corr_local[i, j])
        raw_r = float(corr_raw[i, j])
        lag1_r = float(hgrid_cont[a].corr(hgrid_lag1[b]))
        p_val = _day_block_perm_corr(cam_mats[a], cam_mats[b], loc_r, n_pair_perm, rng)
        link_rows.append({
            "cam_a": a, "cam_b": b,
            "name_a": str(cams.at[a, "name"]), "name_b": str(cams.at[b, "name"]),
            "lat_a": float(cams.at[a, "latitude"]), "lon_a": float(cams.at[a, "longitude"]),
            "lat_b": float(cams.at[b, "latitude"]), "lon_b": float(cams.at[b, "longitude"]),
            "dist_km": round(float(d_km[i, j]), 3),
            "n_hours": overlap,
            "raw_r": raw_r,
            "local_r": loc_r,
            "lag1_r": lag1_r,
            "p_value": p_val,
        })

    corridor_links = pd.DataFrame(link_rows)
    if not corridor_links.empty:
        corridor_links["fdr_q"] = benjamini_hochberg(corridor_links["p_value"].to_numpy())
        corridor_links = corridor_links.sort_values("local_r", ascending=False).reset_index(drop=True)
    return distance_decay, spatial_tests, corridor_links


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshots", type=Path, default=Path("data/processed/l640/rain_snapshots.parquet"))
    parser.add_argument("--osm", type=Path, default=Path("data/interim/osm_context.parquet"))
    parser.add_argument("--dna", type=Path, default=Path("data/processed/dna/camera_dna.parquet"))
    parser.add_argument("--cameras", type=Path, default=Path("data/raw/cctv_info.csv"))
    parser.add_argument("--out", type=Path, default=Path("data/processed/insights"))
    parser.add_argument("--boot", type=int, default=2000)
    parser.add_argument("--perm", type=int, default=5000)
    parser.add_argument("--mantel", type=int, default=2000)
    parser.add_argument("--pair-perm", type=int, default=2000)
    args = parser.parse_args()

    snaps = pd.read_parquet(args.snapshots)
    osm = pd.read_parquet(args.osm)
    info = pd.read_csv(args.cameras)
    dna = pd.read_parquet(args.dna) if args.dna.exists() else None

    vuln = compute_rain_vulnerability(snaps, osm, dna, n_boot=args.boot)
    tidal_pairs, tidal_hourly = compute_tidal_flow(snaps, info, n_perm=args.perm)
    decay, spatial_tests, links = compute_spatial_sync(
        snaps, info, n_mantel=args.mantel, n_pair_perm=args.pair_perm
    )

    args.out.mkdir(parents=True, exist_ok=True)
    vuln.to_csv(args.out / "rain_vulnerability.csv", index=False)
    tidal_pairs.to_csv(args.out / "tidal_pairs.csv", index=False)
    tidal_hourly.to_parquet(args.out / "tidal_hourly.parquet", index=False)
    decay.to_csv(args.out / "distance_decay.csv", index=False)
    spatial_tests.to_csv(args.out / "spatial_tests.csv", index=False)
    links.to_csv(args.out / "corridor_links.csv", index=False)

    pd.set_option("display.float_format", "{:.3f}".format)
    pd.set_option("display.width", 180)
    print("== Idea 4: Rain vulnerability DiD (heavy >5 mm/h vs dry) ==")
    print(vuln[["row_type", "factor", "group_a", "pts_a", "group_b", "pts_b", "did_pts", "did_lo", "did_hi", "boot_p"]].to_string(index=False))
    print("\n== Idea 6: Top 10 tidal reversal co-located pairs (<=100m) ==")
    print(tidal_pairs[["pair_id", "dist_m", "am_asym", "pm_asym", "tidal_swing", "reverses_sign", "weekdays_reversing", "p_value", "fdr_q", "name_a"]].head(10).to_string(index=False))
    print("\n== Idea 2: Spatial synchronization distance decay & Mantel tests ==")
    print(decay.to_string(index=False))
    print(spatial_tests.to_string(index=False))
    print(f"significant corridor links (FDR q < 0.05): {int((links['fdr_q'] < 0.05).sum())} / {len(links)}")
    print(f"\nwrote insight tables to {args.out}")


if __name__ == "__main__":
    main()
