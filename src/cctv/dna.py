"""Step 6b: Traffic DNA clustering and statistical validation across all 100 cameras.

Builds a 6-feature, zoom-invariant temporal rhythm profile per camera from hours 06:00-20:00
(weekday morning/midday/evening/night ratios + overall and morning weekend retention),
clusters cameras with K-Means++, evaluates internal cluster structure against a column-wise
permutation null, and validates discovered archetypes against held-out OpenStreetMap land-use,
road capacity, and rain-impact variables using permutation tests with Benjamini-Hochberg FDR.

Writes data/processed/dna/:
  camera_dna.parquet        per-camera DNA features, PCA coords, cluster_id, archetype, silhouette
  model_selection.csv       k=2..6 silhouette, variance explained (R^2), bootstrap ARI stability
  cluster_profiles.csv      per-archetype DNA means, held-out means, heavy-rain bootstrap delta
  significance_tests.csv    structure permutation tests, external KW/pairwise/FDR tests, mall check
  hourly_archetypes.parquet normalized weekday/weekend hourly curves with 95% camera bootstrap CIs

    uv run python -m cctv.dna
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from cctv.mart import weekend_kept

DNA_FEATURES = ["am_ratio", "midday_ratio", "pm_ratio", "night_ratio", "weekend_keep", "we_am_keep"]
ARCHETYPE_NAMES = {
    0: "All-day urban & retail",
    1: "Evening-peak office / outbound",
    2: "Morning-commute arterial",
}
CBD_LAT, CBD_LON = 13.735, 100.533


def build_dna_features(snaps: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute 6 zoom-invariant Traffic DNA features and normalized 06-20h curves per camera."""
    sub = snaps[snaps["hour"].between(6, 20)]
    piv = sub.groupby(["camera_id", "daytype", "hour"])["n_calibrated"].mean().unstack(["daytype", "hour"])
    cols = [(dt, h) for dt in ("weekday", "weekend") for h in range(6, 21)]
    piv = piv.reindex(columns=pd.MultiIndex.from_tuples(cols, names=["daytype", "hour"]))
    for dt in ("weekday", "weekend"):
        missing_per_cam = piv[dt].isna().sum(axis=1)
        if (missing_per_cam > 2).any():
            bad = missing_per_cam[missing_per_cam > 2].to_dict()
            raise ValueError(f"Cameras missing >2 hours in {dt} 06:00-20:00: {bad}")
        if (missing_per_cam > 0).any():
            piv[dt] = piv[dt].interpolate(axis=1, limit_direction="both")
    if piv.isna().any().any():
        missing = int(piv.isna().sum().sum())
        raise ValueError(f"Expected complete 06:00-20:00 profiles, found {missing} missing cells")

    wd, we = piv["weekday"], piv["weekend"]
    wd_mean = wd.mean(axis=1)
    dna = pd.DataFrame(
        {
            "am_ratio": wd[[6, 7, 8, 9]].mean(axis=1) / wd_mean,
            "midday_ratio": wd[[10, 11, 12, 13, 14, 15]].mean(axis=1) / wd_mean,
            "pm_ratio": wd[[16, 17, 18, 19]].mean(axis=1) / wd_mean,
            "night_ratio": wd[[19, 20]].mean(axis=1) / wd_mean,
            "weekend_keep": we.sum(axis=1) / wd.sum(axis=1),
            "we_am_keep": we[[6, 7, 8, 9]].mean(axis=1) / wd[[6, 7, 8, 9]].mean(axis=1),
        },
        index=piv.index,
    )
    hourly_norm = piv.div(wd_mean, axis=0)
    return dna, hourly_norm


def kmeans_pp(X: np.ndarray, k: int, n_init: int = 80, seed: int = 403) -> tuple[np.ndarray, np.ndarray, float]:
    """Pure-NumPy K-Means++ returning (labels, centers, inertia) from best of n_init restarts."""
    rng = np.random.default_rng(seed)
    n = len(X)
    best_inertia, best_labels, best_centers = np.inf, np.zeros(n, dtype=int), np.empty((k, X.shape[1]))
    for _ in range(n_init):
        centers = [X[rng.integers(n)]]
        for _ in range(1, k):
            d2 = np.min([np.sum((X - c) ** 2, axis=1) for c in centers], axis=0)
            total = d2.sum()
            probs = d2 / total if total > 0 else np.full(n, 1.0 / n)
            centers.append(X[rng.choice(n, p=probs)])
        centers_arr = np.array(centers, dtype=float)
        for _ in range(100):
            dists = np.sum((X[:, None, :] - centers_arr[None, :, :]) ** 2, axis=2)
            labels = np.argmin(dists, axis=1)
            new_centers = np.array(
                [X[labels == j].mean(axis=0) if np.any(labels == j) else centers_arr[j] for j in range(k)]
            )
            if np.allclose(new_centers, centers_arr):
                centers_arr = new_centers
                break
            centers_arr = new_centers
        inertia = float(np.sum((X - centers_arr[labels]) ** 2))
        if inertia < best_inertia:
            best_inertia, best_labels, best_centers = inertia, labels, centers_arr
    return best_labels, best_centers, best_inertia


def silhouette_samples(X: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Euclidean silhouette score in [-1, 1] for each sample."""
    dmat = np.sqrt(np.maximum(0.0, np.sum((X[:, None, :] - X[None, :, :]) ** 2, axis=2)))
    n = len(X)
    unique = np.unique(labels)
    sil = np.zeros(n, dtype=float)
    if len(unique) < 2:
        return sil
    for i in range(n):
        same = labels == labels[i]
        a = dmat[i, same].sum() / (same.sum() - 1) if same.sum() > 1 else 0.0
        b = min(dmat[i, labels == j].mean() for j in unique if j != labels[i])
        denom = max(a, b)
        sil[i] = (b - a) / denom if denom > 0 else 0.0
    return sil


def adjusted_rand_index(a: np.ndarray, b: np.ndarray) -> float:
    """Adjusted Rand Index between two label vectors of equal length."""
    n = len(a)
    if n < 2:
        return 1.0
    _, ia = np.unique(a, return_inverse=True)
    _, ib = np.unique(b, return_inverse=True)
    tab = np.zeros((ia.max() + 1, ib.max() + 1), dtype=float)
    np.add.at(tab, (ia, ib), 1.0)
    comb2 = lambda x: x * (x - 1.0) / 2.0  # noqa: E731
    sum_ij = comb2(tab).sum()
    sum_i = comb2(tab.sum(axis=1)).sum()
    sum_j = comb2(tab.sum(axis=0)).sum()
    tot = comb2(float(n))
    if tot == 0:
        return 1.0
    expected = sum_i * sum_j / tot
    denom = 0.5 * (sum_i + sum_j) - expected
    return float((sum_ij - expected) / denom) if denom > 0 else 0.0


def bootstrap_stability(
    X: np.ndarray, k: int, base_labels: np.ndarray, n_boot: int = 50, frac: float = 0.85, seed: int = 403
) -> float:
    """Mean Adjusted Rand Index across subsamples without replacement."""
    rng = np.random.default_rng(seed)
    n = len(X)
    m = max(k + 1, int(round(frac * n)))
    aris = []
    for b in range(n_boot):
        idx = rng.choice(n, size=m, replace=False)
        lbl, _, _ = kmeans_pp(X[idx], k, n_init=15, seed=seed + b + 1)
        aris.append(adjusted_rand_index(base_labels[idx], lbl))
    return float(np.mean(aris))


def pca_2d(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Centered SVD returning 2D projections and explained variance ratios with deterministic signs."""
    xc = X - X.mean(axis=0, keepdims=True)
    u, s, vt = np.linalg.svd(xc, full_matrices=False)
    coords = u[:, :2] * s[:2]
    for col in range(min(2, vt.shape[0])):
        if vt[col, np.argmax(np.abs(vt[col]))] < 0:
            coords[:, col] *= -1
    tot_var = float(np.sum(s ** 2))
    var_ratio = (s[:2] ** 2) / tot_var if tot_var > 0 else np.zeros(2)
    return coords, var_ratio


def assign_archetype_names(dna: pd.DataFrame, labels: np.ndarray) -> tuple[np.ndarray, pd.Series]:
    """Deterministically remap cluster IDs and assign interpretable archetype names."""
    unique = np.unique(labels)
    if len(unique) == 3:
        pm_means = {c: float(dna.loc[labels == c, "pm_ratio"].mean()) for c in unique}
        evening_old = max(unique, key=lambda c: pm_means[c])
        rem = [c for c in unique if c != evening_old]
        wk_means = {c: float(dna.loc[labels == c, "weekend_keep"].mean()) for c in rem}
        allday_old = max(rem, key=lambda c: wk_means[c])
        morning_old = [c for c in rem if c != allday_old][0]
        mapping = {allday_old: 0, evening_old: 1, morning_old: 2}
        new_labels = np.array([mapping[int(c)] for c in labels], dtype=int)
        names = pd.Series([ARCHETYPE_NAMES[c] for c in new_labels], index=dna.index, name="archetype")
        return new_labels, names

    order = sorted(unique, key=lambda c: float(dna.loc[labels == c, "weekend_keep"].mean()), reverse=True)
    mapping = {old: new for new, old in enumerate(order)}
    new_labels = np.array([mapping[int(c)] for c in labels], dtype=int)
    names = pd.Series([f"Cluster {c}" for c in new_labels], index=dna.index, name="archetype")
    return new_labels, names


def _kw_from_ranks(ranks: np.ndarray, groups: np.ndarray, unique_groups: np.ndarray, tie_corr: float) -> float:
    n = len(ranks)
    h_sum = sum((ranks[groups == g].sum() ** 2) / int((groups == g).sum()) for g in unique_groups)
    h = (12.0 / (n * (n + 1))) * h_sum - 3.0 * (n + 1)
    return float(h / tie_corr) if tie_corr > 0 else 0.0


def _tie_correction(values: np.ndarray) -> float:
    n = len(values)
    if n < 2:
        return 1.0
    _, counts = np.unique(values, return_counts=True)
    return float(1.0 - np.sum(counts ** 3 - counts) / (n ** 3 - n))


def kruskal_wallis_stat(values: np.ndarray, groups: np.ndarray) -> float:
    """Tie-corrected Kruskal-Wallis H statistic across groups."""
    mask = ~np.isnan(values)
    v, g = values[mask], groups[mask]
    unique = np.unique(g)
    if len(unique) < 2 or len(v) < 3:
        return 0.0
    ranks = pd.Series(v).rank().to_numpy()
    return _kw_from_ranks(ranks, g, unique, _tie_correction(v))


def kruskal_wallis_perm(
    values: np.ndarray, groups: np.ndarray, n_perm: int = 10_000, seed: int = 403
) -> tuple[float, float]:
    """Kruskal-Wallis H statistic and permutation p-value (handles ties and small samples)."""
    mask = ~np.isnan(values)
    v, g = values[mask], groups[mask]
    unique = np.unique(g)
    if len(unique) < 2 or len(v) < 3:
        return 0.0, 1.0
    ranks = pd.Series(v).rank().to_numpy()
    tie_corr = _tie_correction(v)
    obs = _kw_from_ranks(ranks, g, unique, tie_corr)
    rng = np.random.default_rng(seed)
    ge = 0
    for _ in range(n_perm):
        if _kw_from_ranks(ranks, rng.permutation(g), unique, tie_corr) >= obs - 1e-12:
            ge += 1
    return obs, float((ge + 1) / (n_perm + 1))


def pairwise_diff_perm(
    a: np.ndarray, b: np.ndarray, n_perm: int = 10_000, seed: int = 403
) -> tuple[float, float]:
    """Two-sided permutation test for difference in means (mean(a) - mean(b))."""
    va = np.asarray(a, dtype=float)
    vb = np.asarray(b, dtype=float)
    va, vb = va[~np.isnan(va)], vb[~np.isnan(vb)]
    if len(va) == 0 or len(vb) == 0:
        return float("nan"), 1.0
    obs = float(va.mean() - vb.mean())
    pool = np.concatenate([va, vb])
    na, n_tot = len(va), len(pool)
    tot_sum = float(pool.sum())
    rng = np.random.default_rng(seed)
    ge = 0
    batch_size = min(2000, n_perm)
    for start in range(0, n_perm, batch_size):
        m = min(batch_size, n_perm - start)
        idx = np.argsort(rng.random((m, n_tot)), axis=1)[:, :na]
        sum_a = pool[idx].sum(axis=1)
        diffs = sum_a / na - (tot_sum - sum_a) / (n_tot - na)
        ge += int(np.sum(np.abs(diffs) >= abs(obs) - 1e-12))
    return obs, float((ge + 1) / (n_perm + 1))


def benjamini_hochberg(p_values: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg false discovery rate (FDR) adjusted q-values."""
    p = np.asarray(p_values, dtype=float)
    m = len(p)
    if m == 0:
        return p
    order = np.argsort(p)
    ranks = np.arange(1, m + 1, dtype=float)
    q_sorted = np.minimum.accumulate((p[order] * m / ranks)[::-1])[::-1]
    q = np.empty(m, dtype=float)
    q[order] = np.clip(q_sorted, 0.0, 1.0)
    return q


def structure_permutation_test(
    X: np.ndarray, k: int, obs_r2: float, obs_sil: float, n_perm: int = 300, seed: int = 403
) -> dict[str, float]:
    """Compare observed R^2 and silhouette against independent column-permutation nulls."""
    tot_ss = float(np.sum((X - X.mean(axis=0, keepdims=True)) ** 2))
    rng = np.random.default_rng(seed)
    null_r2, null_sil = [], []
    for b in range(n_perm):
        xp = np.column_stack([rng.permutation(X[:, j]) for j in range(X.shape[1])])
        lp, _, inertia = kmeans_pp(xp, k, n_init=10, seed=seed + b + 1)
        null_r2.append(1.0 - inertia / tot_ss if tot_ss > 0 else 0.0)
        null_sil.append(float(silhouette_samples(xp, lp).mean()))
    nr2, nsil = np.array(null_r2), np.array(null_sil)
    return {
        "r2_null_mean": float(nr2.mean()),
        "r2_null_max": float(nr2.max()),
        "p_r2": float((np.sum(nr2 >= obs_r2 - 1e-12) + 1) / (n_perm + 1)),
        "sil_null_mean": float(nsil.mean()),
        "sil_null_max": float(nsil.max()),
        "p_sil": float((np.sum(nsil >= obs_sil - 1e-12) + 1) / (n_perm + 1)),
    }


def _heavy_rain_cluster_boot(df: pd.DataFrame, n_boot: int = 1000, seed: int = 403) -> tuple[float, float, float, int]:
    """Camera-day cluster bootstrap of heavy (>5 mm/h) minus dry excess_calibrated."""
    heavy = df["rain_now"] > 5
    dry = ~df["wet"]
    cl = df["camera_id"].astype(str) + "_" + df["timestamp"].dt.date.astype(str)
    all_cl = cl.unique()
    h_sum = df.loc[heavy].groupby(cl)["excess_calibrated"].sum().reindex(all_cl, fill_value=0.0).to_numpy()
    h_n = df.loc[heavy].groupby(cl).size().reindex(all_cl, fill_value=0).to_numpy()
    d_sum = df.loc[dry].groupby(cl)["excess_calibrated"].sum().reindex(all_cl, fill_value=0.0).to_numpy()
    d_n = df.loc[dry].groupby(cl).size().reindex(all_cl, fill_value=0).to_numpy()
    if h_n.sum() == 0 or d_n.sum() == 0:
        return float("nan"), float("nan"), float("nan"), int(h_n.sum())
    pt = float(100 * (np.expm1(h_sum.sum() / h_n.sum()) - np.expm1(d_sum.sum() / d_n.sum())))
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(all_cl), size=len(all_cl))
        hn, dn = h_n[idx].sum(), d_n[idx].sum()
        if hn > 0 and dn > 0:
            draws.append(100 * (np.expm1(h_sum[idx].sum() / hn) - np.expm1(d_sum[idx].sum() / dn)))
    arr = np.array(draws)
    return pt, float(np.quantile(arr, 0.025)), float(np.quantile(arr, 0.975)), int(h_n.sum())


def _hourly_archetypes(hourly_norm: pd.DataFrame, labels: np.ndarray, n_boot: int = 400, seed: int = 403) -> pd.DataFrame:
    """Mean and 95% camera bootstrap CI of normalized traffic per archetype x daytype x hour."""
    rng = np.random.default_rng(seed)
    rows = []
    for cid in sorted(np.unique(labels)):
        sub = hourly_norm.loc[labels == cid]
        arr = sub.to_numpy()
        n = len(arr)
        boot_idx = rng.integers(0, n, size=(n_boot, n))
        boot_means = arr[boot_idx].mean(axis=1)
        lo = np.quantile(boot_means, 0.025, axis=0)
        hi = np.quantile(boot_means, 0.975, axis=0)
        mean = arr.mean(axis=0)
        arch = ARCHETYPE_NAMES.get(int(cid), f"Cluster {cid}")
        for j, (daytype, hour) in enumerate(sub.columns):
            rows.append({
                "cluster_id": int(cid), "archetype": arch, "daytype": daytype, "hour": int(hour),
                "rel_traffic": float(mean[j]), "rel_lo": float(lo[j]), "rel_hi": float(hi[j]),
            })
    return pd.DataFrame(rows)


def run_dna(
    snaps: pd.DataFrame,
    osm: pd.DataFrame,
    info: pd.DataFrame,
    k: int = 3,
    n_perm: int = 10_000,
    structure_perm: int = 300,
    seed: int = 403,
) -> dict[str, pd.DataFrame]:
    """Execute full Traffic DNA clustering, model selection, and statistical validation."""
    dna, hourly_norm = build_dna_features(snaps)
    cam_ids = dna.index.to_numpy()
    X = ((dna - dna.mean()) / dna.std(ddof=0)).to_numpy()
    tot_ss = float(np.sum((X - X.mean(axis=0, keepdims=True)) ** 2))

    # 1. Model selection across k = 2..6
    sel_rows = []
    chosen_labels = np.zeros(len(X), dtype=int)
    chosen_r2, chosen_sil = 0.0, 0.0
    for kk in range(2, 7):
        lbl, _, inertia = kmeans_pp(X, kk, n_init=80, seed=seed)
        r2 = 1.0 - inertia / tot_ss if tot_ss > 0 else 0.0
        sil = float(silhouette_samples(X, lbl).mean())
        ari = bootstrap_stability(X, kk, lbl, n_boot=50, seed=seed)
        counts = sorted([int((lbl == j).sum()) for j in range(kk)], reverse=True)
        sel_rows.append({
            "k": kk, "silhouette": sil, "r2": r2, "boot_ari": ari,
            "min_cluster_size": min(counts), "sizes": ",".join(map(str, counts)),
        })
        if kk == k:
            chosen_labels, chosen_r2, chosen_sil = lbl, r2, sil
    model_selection = pd.DataFrame(sel_rows)

    cluster_id, archetype = assign_archetype_names(dna, chosen_labels)
    sil_samples = silhouette_samples(X, cluster_id)
    coords, var_ratio = pca_2d(X)

    camera_dna = dna.copy()
    camera_dna["pca1"] = coords[:, 0]
    camera_dna["pca2"] = coords[:, 1]
    camera_dna["pca1_var"] = float(var_ratio[0])
    camera_dna["pca2_var"] = float(var_ratio[1])
    camera_dna["cluster_id"] = cluster_id
    camera_dna["archetype"] = archetype
    camera_dna["silhouette"] = sil_samples
    camera_dna = camera_dna.reset_index()

    # 2. Internal cluster structure permutation test
    struct = structure_permutation_test(X, k, chosen_r2, chosen_sil, n_perm=structure_perm, seed=seed)

    # 3. Held-out external validation (features never used during clustering)
    ext = info[["camera_id", "latitude", "longitude"]].merge(osm, on="camera_id", how="left").set_index("camera_id")
    ext = ext.loc[cam_ids].copy()
    k_m = 111.32
    ext["dist_cbd_km"] = np.hypot(
        (ext["latitude"] - CBD_LAT) * k_m,
        (ext["longitude"] - CBD_LON) * k_m * np.cos(np.radians(CBD_LAT)),
    )
    ext["urban_core_pois_500m"] = (
        ext["n_mall_market_500m"] + ext["n_hospital_500m"] + ext["n_rail_station_500m"]
    )
    ext["mean_calibrated"] = snaps.groupby("camera_id")["n_calibrated"].mean().reindex(cam_ids)
    ext["moto_share_pct"] = (
        100 * snaps.groupby("camera_id")["n_motorcycle"].sum() / snaps.groupby("camera_id")["n_vehicles"].sum()
    ).reindex(cam_ids)
    e = snaps.groupby(["camera_id", "wet"])["excess_calibrated"].agg(["mean", "size"]).unstack()
    ok = (e[("size", True)] >= 10) & (e[("size", False)] >= 10)
    ext["rain_effect_pct"] = (100 * (np.expm1(e[("mean", True)]) - np.expm1(e[("mean", False)]))).where(ok).reindex(cam_ids)
    ext["weekend_kept_pct"] = weekend_kept(snaps)["weekend_kept_pct"].reindex(cam_ids)

    heldout_feats = [
        "urban_core_pois_500m", "n_hospital_500m", "n_mall_market_500m", "n_rail_station_500m", "n_school_500m",
        "n_traffic_signals_500m", "n_traffic_signals_100m", "n_bus_stop_500m", "lanes", "maxspeed_kmh",
        "is_bridge", "dist_cbd_km", "mean_calibrated", "moto_share_pct", "rain_effect_pct",
    ]
    ext_rows = []
    for feat in heldout_feats:
        vals = ext[feat].to_numpy(dtype=float)
        h_stat, p_kw = kruskal_wallis_perm(vals, cluster_id, n_perm=n_perm, seed=seed)
        _, p_02 = pairwise_diff_perm(vals[cluster_id == 0], vals[cluster_id == 2], n_perm=n_perm, seed=seed)
        ext_rows.append({
            "test_type": "external_kw",
            "feature": feat,
            "statistic": h_stat,
            "null_mean": float("nan"),
            "p_value": p_kw,
            "fdr_q": float("nan"),
            "p_allday_vs_morning": p_02,
            "mean_all_day": float(np.nanmean(vals[cluster_id == 0])),
            "mean_evening": float(np.nanmean(vals[cluster_id == 1])),
            "mean_morning": float(np.nanmean(vals[cluster_id == 2])),
        })
    ext_df = pd.DataFrame(ext_rows)
    ext_df["fdr_q"] = benjamini_hochberg(ext_df["p_value"].to_numpy())

    # 4. Reproducible report.md check: malls >= 3 vs 0 on weekend traffic retention
    malls_3plus = ext.loc[ext["n_mall_market_500m"] >= 3, "weekend_kept_pct"].to_numpy(dtype=float)
    malls_0 = ext.loc[ext["n_mall_market_500m"] == 0, "weekend_kept_pct"].to_numpy(dtype=float)
    mall_diff, mall_p = pairwise_diff_perm(malls_3plus, malls_0, n_perm=n_perm, seed=seed)

    struct_rows = pd.DataFrame([
        {
            "test_type": "structure_perm", "feature": "cluster_r2", "statistic": chosen_r2,
            "null_mean": struct["r2_null_mean"], "p_value": struct["p_r2"], "fdr_q": float("nan"),
            "p_allday_vs_morning": float("nan"), "mean_all_day": float("nan"),
            "mean_evening": float("nan"), "mean_morning": float("nan"),
        },
        {
            "test_type": "structure_perm", "feature": "cluster_silhouette", "statistic": chosen_sil,
            "null_mean": struct["sil_null_mean"], "p_value": struct["p_sil"], "fdr_q": float("nan"),
            "p_allday_vs_morning": float("nan"), "mean_all_day": float("nan"),
            "mean_evening": float("nan"), "mean_morning": float("nan"),
        },
        {
            "test_type": "hypothesis_check", "feature": "weekend_kept_malls_3plus_vs_0", "statistic": mall_diff,
            "null_mean": 0.0, "p_value": mall_p, "fdr_q": float("nan"),
            "p_allday_vs_morning": float("nan"),
            "mean_all_day": float(np.nanmean(malls_3plus)),
            "mean_evening": float("nan"),
            "mean_morning": float(np.nanmean(malls_0)),
        },
    ])
    significance_tests = pd.concat([struct_rows, ext_df], ignore_index=True)

    # 5. Per-cluster summary + heavy-rain bootstrap delta
    snaps_c = snaps.merge(camera_dna[["camera_id", "cluster_id"]], on="camera_id", how="left")
    prof_rows = []
    for cid in sorted(np.unique(cluster_id)):
        mask = cluster_id == cid
        pt, lo, hi, n_heavy = _heavy_rain_cluster_boot(snaps_c[snaps_c["cluster_id"] == cid], n_boot=1000, seed=seed)
        row = {"cluster_id": int(cid), "archetype": ARCHETYPE_NAMES.get(int(cid), f"Cluster {cid}"), "n_cameras": int(mask.sum())}
        for feat in DNA_FEATURES:
            row[feat] = float(dna.loc[mask, feat].mean())
        row.update({
            "mean_urban_core_pois": float(ext.loc[mask, "urban_core_pois_500m"].mean()),
            "mean_malls": float(ext.loc[mask, "n_mall_market_500m"].mean()),
            "mean_hospitals": float(ext.loc[mask, "n_hospital_500m"].mean()),
            "mean_calibrated": float(ext.loc[mask, "mean_calibrated"].mean()),
            "heavy_vs_dry_pts": pt, "heavy_lo": lo, "heavy_hi": hi, "n_heavy": n_heavy,
        })
        prof_rows.append(row)
    cluster_profiles = pd.DataFrame(prof_rows)
    hourly_archetypes = _hourly_archetypes(hourly_norm, cluster_id, n_boot=400, seed=seed)

    return {
        "camera_dna": camera_dna,
        "model_selection": model_selection,
        "cluster_profiles": cluster_profiles,
        "significance_tests": significance_tests,
        "hourly_archetypes": hourly_archetypes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshots", type=Path, default=Path("data/processed/l640/rain_snapshots.parquet"))
    parser.add_argument("--osm", type=Path, default=Path("data/interim/osm_context.parquet"))
    parser.add_argument("--cameras", type=Path, default=Path("data/raw/cctv_info.csv"))
    parser.add_argument("--out", type=Path, default=Path("data/processed/dna"))
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--perm", type=int, default=10_000)
    parser.add_argument("--structure-perm", type=int, default=300)
    args = parser.parse_args()

    res = run_dna(
        pd.read_parquet(args.snapshots),
        pd.read_parquet(args.osm),
        pd.read_csv(args.cameras),
        k=args.k, n_perm=args.perm, structure_perm=args.structure_perm,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    res["camera_dna"].to_parquet(args.out / "camera_dna.parquet", index=False)
    res["model_selection"].to_csv(args.out / "model_selection.csv", index=False)
    res["cluster_profiles"].to_csv(args.out / "cluster_profiles.csv", index=False)
    res["significance_tests"].to_csv(args.out / "significance_tests.csv", index=False)
    res["hourly_archetypes"].to_parquet(args.out / "hourly_archetypes.parquet", index=False)

    pd.set_option("display.float_format", "{:.3f}".format)
    pd.set_option("display.width", 160)
    print("== model selection (Traffic DNA K-Means++) ==")
    print(res["model_selection"].to_string(index=False))
    print("\n== cluster profiles ==")
    print(res["cluster_profiles"].to_string(index=False))
    print("\n== statistical validation (permutation tests & FDR) ==")
    print(res["significance_tests"].to_string(index=False))
    print(f"\nwrote Traffic DNA tables to {args.out}")


if __name__ == "__main__":
    main()
