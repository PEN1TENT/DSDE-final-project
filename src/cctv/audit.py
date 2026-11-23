"""Step 1b & 7b: CCTV frame quality audit and spatial-temporal traffic shock detector.

Two stages run around `cctv.rain`:
  --stage frames   catches blank/whiteout frames (contrast < 10) and watermark-overlaid
                   frozen feeds missed by MD5 (central 15%-85% pixel MAD < 1.0).
  --stage shocks   flags camera-hour anomalies (|z| >= 2.5) on cleaned snapshots as
                   citywide, corridor, or localized shocks, and isolates Mon 31 Aug evening.

    uv run python -m cctv.audit --stage frames
    uv run python -m cctv.audit --stage shocks
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import pandas as pd


def audit_frames(images: pd.DataFrame, raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Flag blank/whiteout frames and watermark-frozen feeds via central pixel MAD."""
    df = images.sort_values(["camera_id", "timestamp", "path"], ignore_index=True).copy()
    df["camera_id"] = df["camera_id"].astype(int)
    df["blank"] = df["contrast"].fillna(0.0) < 10.0
    df["whiteout"] = df["blank"] & (df["brightness"].fillna(0.0) >= 250.0)

    same_cam = df["camera_id"] == df["camera_id"].shift()
    db = (df["brightness"] - df["brightness"].shift()).abs()
    dc = (df["contrast"] - df["contrast"].shift()).abs()
    ds = (df["sharpness"] - df["sharpness"].shift()).abs()
    candidates = same_cam & (db < 0.5) & (dc < 0.5) & (ds < 10.0) & (~df["blank"]) & df["readable"]

    center_mad = np.full(len(df), np.nan, dtype=float)
    base_frozen = df["frozen"].fillna(False).to_numpy(dtype=bool) if "frozen" in df.columns else np.zeros(len(df), dtype=bool)
    visual_frozen = base_frozen.copy()

    cache_prev_idx = -1
    cache_prev_crop: np.ndarray | None = None
    for idx in df.index[candidates]:
        if idx - 1 == cache_prev_idx and cache_prev_crop is not None:
            im1 = cache_prev_crop
        else:
            raw1 = cv2.imread(str(raw_dir / df.at[idx - 1, "path"]), cv2.IMREAD_GRAYSCALE)
            if raw1 is not None:
                h1 = raw1.shape[0]
                im1 = raw1[int(0.15 * h1) : int(0.85 * h1)]
            else:
                im1 = None

        raw2 = cv2.imread(str(raw_dir / df.at[idx, "path"]), cv2.IMREAD_GRAYSCALE)
        if raw2 is not None:
            h2 = raw2.shape[0]
            im2 = raw2[int(0.15 * h2) : int(0.85 * h2)]
        else:
            im2 = None

        cache_prev_idx = int(idx)
        cache_prev_crop = im2

        if im1 is not None and im2 is not None and im1.shape == im2.shape and im1.size > 0:
            mad = float(np.abs(im1.astype(float) - im2.astype(float)).mean())
            center_mad[idx] = mad
            if mad < 1.0:
                visual_frozen[idx] = True

    df["center_mad"] = center_mad
    df["visual_frozen"] = visual_frozen
    df["usable"] = df["readable"].astype(bool) & (~df["blank"]) & (~df["visual_frozen"])

    frame_audit = df[["path", "camera_id", "timestamp", "blank", "whiteout", "visual_frozen", "center_mad", "usable"]].copy()

    g = df.groupby("camera_id")
    camera_health = pd.DataFrame({
        "total_frames": g.size(),
        "blank_frames": g["blank"].sum().astype(int),
        "whiteout_frames": g["whiteout"].sum().astype(int),
        "visual_frozen_frames": g["visual_frozen"].sum().astype(int),
        "usable_frames": g["usable"].sum().astype(int),
    }).reset_index()
    camera_health["bad_pct"] = 100.0 * (1.0 - camera_health["usable_frames"] / camera_health["total_frames"])
    camera_health = camera_health.sort_values("bad_pct", ascending=False).reset_index(drop=True)

    stamped = df.dropna(subset=["timestamp"]).copy()
    stamped["date_str"] = stamped["timestamp"].dt.strftime("%Y-%m-%d")
    stamped["hour"] = stamped["timestamp"].dt.hour
    bad = stamped[~stamped["usable"]]
    hg = stamped.groupby(["date_str", "hour"])
    hourly_outages = pd.DataFrame({
        "total_frames": hg.size(),
        "blank_frames": hg["blank"].sum().astype(int),
        "whiteout_frames": hg["whiteout"].sum().astype(int),
        "visual_frozen_frames": hg["visual_frozen"].sum().astype(int),
        "affected_cameras": bad.groupby(["date_str", "hour"])["camera_id"].nunique(),
    }).fillna(0).reset_index()
    hourly_outages["affected_cameras"] = hourly_outages["affected_cameras"].astype(int)
    return frame_audit, camera_health, hourly_outages


def _camera_xy_km(info: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Local equirectangular km coordinates aligned with info.index."""
    lat0 = float(info["latitude"].mean())
    x = info["longitude"].to_numpy(float) * 111.32 * np.cos(np.radians(lat0))
    y = info["latitude"].to_numpy(float) * 111.32
    return x, y


def detect_shocks(
    snaps: pd.DataFrame, info: pd.DataFrame, z_thresh: float = 2.5, neighbor_km: float = 2.0
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Detect camera-hour traffic shocks (|z| >= z_thresh) and inspect Mon 31 Aug evening."""
    df = snaps.copy()
    df["camera_id"] = df["camera_id"].astype(int)
    df["date_str"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    if "hour" not in df.columns:
        df["hour"] = df["timestamp"].dt.hour

    cams = info.copy()
    cams["camera_id"] = cams["camera_id"].astype(int)
    cams["name"] = np.where(
        cams["location_en"].str.contains("connect BMAcctv", na=True),
        cams["location"],
        cams["location_en"],
    )
    cams = cams.set_index("camera_id")

    grp_cols = ["camera_id", "date_str", "hour"]
    ch = df.groupby(grp_cols, as_index=False).agg(
        n=("path", "size"),
        excess_mean=("excess_calibrated", "mean"),
        cal_mean=("n_calibrated", "mean"),
        rain_mean=("rain_now", "mean"),
        bright_mean=("brightness", "mean") if "brightness" in df.columns else ("n_calibrated", "mean"),
    )
    ch = ch[ch["n"] >= 3].copy()

    # Representative raw image for each camera-hour: frame most matching the hour's direction
    idx_max = df.groupby(grp_cols)["excess_calibrated"].idxmax()
    idx_min = df.groupby(grp_cols)["excess_calibrated"].idxmin()
    max_paths = df.loc[idx_max].set_index(grp_cols)["path"]
    min_paths = df.loc[idx_min].set_index(grp_cols)["path"]
    keys = pd.MultiIndex.from_frame(ch[grp_cols])
    ch["rep_path"] = np.where(
        ch["excess_mean"] >= 0,
        max_paths.reindex(keys).to_numpy(),
        min_paths.reindex(keys).to_numpy(),
    )

    std = float(ch["excess_mean"].std(ddof=0))
    mean = float(ch["excess_mean"].mean())
    ch["z_score"] = (ch["excess_mean"] - mean) / std if std > 0 else 0.0
    ch["pct_vs_usual"] = 100.0 * np.expm1(ch["excess_mean"])

    city_z = ch.groupby(["date_str", "hour"])["z_score"].mean().rename("citywide_z")
    ch = ch.merge(city_z, on=["date_str", "hour"], how="left")

    cam_ids = cams.index.to_numpy()
    x, y = _camera_xy_km(cams)
    dmat = np.sqrt((x[:, None] - x[None, :]) ** 2 + (y[:, None] - y[None, :]) ** 2)
    neighbors_map = {
        int(cam_ids[i]): set(int(cam_ids[j]) for j in range(len(cam_ids)) if i != j and dmat[i, j] <= neighbor_km)
        for i in range(len(cam_ids))
    }

    z_lookup = ch.set_index(["date_str", "hour", "camera_id"])["z_score"]
    # Build per-slot dict once so neighbor lookups stay O(n)
    slot_cams: dict[tuple[str, int], dict[int, float]] = {}
    for (d_str, hr, cid), val in z_lookup.items():
        slot_cams.setdefault((d_str, int(hr)), {})[int(cid)] = float(val)

    nb_z = []
    for row in ch.itertuples():
        nb_ids = neighbors_map.get(int(row.camera_id), set())
        slot = slot_cams.get((row.date_str, int(row.hour)), {})
        vals = [slot[nb] for nb in nb_ids if nb in slot]
        nb_z.append(float(np.mean(vals)) if vals else np.nan)
    ch["neighbor_z"] = nb_z

    shocks = ch[ch["z_score"].abs() >= z_thresh].copy()
    cond_city = shocks["citywide_z"].abs() >= 1.0
    cond_corr = shocks["neighbor_z"].notna() & (shocks["neighbor_z"].abs() >= 1.0) & (~cond_city)
    shocks["shock_type"] = np.where(cond_city, "citywide_shock", np.where(cond_corr, "corridor_shock", "localized_shock"))
    shocks["name"] = shocks["camera_id"].map(cams["name"])
    shocks = shocks.sort_values("z_score", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)

    eve = df[df["hour"] >= 17]
    daily_evening = (
        eve.groupby(["date_str", "wet"], as_index=False)
        .agg(
            snapshots=("path", "size"),
            pct_vs_usual=("excess_calibrated", lambda s: 100.0 * np.expm1(s.mean())),
            raw_mean=("n_vehicles", "mean"),
            cal_mean=("n_calibrated", "mean"),
            brightness=("brightness", "mean"),
            sharpness=("sharpness", "median"),
            rain_mean=("rain_now", "mean"),
        )
        .sort_values(["date_str", "wet"])
        .reset_index(drop=True)
    )

    m31 = df[df["date_str"] == "2026-08-31"]
    mon31_hourly = (
        m31.groupby("hour", as_index=False)
        .agg(
            snapshots=("path", "size"),
            pct_vs_usual=("excess_calibrated", lambda s: 100.0 * np.expm1(s.mean())),
            rain_mean=("rain_now", "mean"),
            wet_share=("wet", "mean"),
            brightness=("brightness", "mean"),
        )
        .sort_values("hour")
        .reset_index(drop=True)
    )
    return shocks, daily_evening, mon31_hourly


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=["frames", "shocks"], required=True)
    parser.add_argument("--raw", type=Path, default=Path("data/raw/cctv_images"))
    parser.add_argument("--images", type=Path, default=Path("data/interim/images.parquet"))
    parser.add_argument("--snapshots", type=Path, default=Path("data/processed/l640/rain_snapshots.parquet"))
    parser.add_argument("--cameras", type=Path, default=Path("data/raw/cctv_info.csv"))
    parser.add_argument("--frame-audit", type=Path, default=Path("data/interim/frame_audit.parquet"))
    parser.add_argument("--out", type=Path, default=Path("data/processed/audit"))
    parser.add_argument("--z-thresh", type=float, default=2.5)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    if args.stage == "frames":
        frame_audit, cam_health, hourly_out = audit_frames(pd.read_parquet(args.images), args.raw)
        args.frame_audit.parent.mkdir(parents=True, exist_ok=True)
        frame_audit.to_parquet(args.frame_audit, index=False)
        cam_health.to_csv(args.out / "camera_health.csv", index=False)
        hourly_out.to_csv(args.out / "hourly_outages.csv", index=False)
        n_tot = len(frame_audit)
        print(
            f"audited {n_tot} frames -> usable={int(frame_audit['usable'].sum())}, "
            f"blank={int(frame_audit['blank'].sum())} (whiteout={int(frame_audit['whiteout'].sum())}), "
            f"visual_frozen={int(frame_audit['visual_frozen'].sum())}"
        )
        print(f"wrote {args.frame_audit}, {args.out / 'camera_health.csv'}, {args.out / 'hourly_outages.csv'}")
    else:
        shocks, daily_eve, mon31 = detect_shocks(
            pd.read_parquet(args.snapshots), pd.read_csv(args.cameras), z_thresh=args.z_thresh
        )
        shocks.to_csv(args.out / "traffic_shocks.csv", index=False)
        daily_eve.to_csv(args.out / "daily_evening_audit.csv", index=False)
        mon31.to_csv(args.out / "mon31_hourly.csv", index=False)
        print(f"detected {len(shocks)} traffic shocks (|z| >= {args.z_thresh}): {shocks['shock_type'].value_counts().to_dict()}")
        print(f"wrote {args.out / 'traffic_shocks.csv'}, {args.out / 'daily_evening_audit.csv'}, {args.out / 'mon31_hourly.csv'}")


if __name__ == "__main__":
    main()
