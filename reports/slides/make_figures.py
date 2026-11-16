"""Extra figures for the slide deck (the report charts come from cctv.charts).

    uv run python reports/slides/make_figures.py

Writes reports/slides/fig/*.png: camera map, weekend map and bar chart, hourly profile, vehicle mix,
and two example frames with detector boxes (dry day, wet night).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import patheffects  # noqa: E402
import pandas as pd  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from cctv.charts import BLUE, GRID, INK2, ORANGE, SURFACE  # noqa: E402,F401  (also sets rcParams)

ROOT = Path(__file__).resolve().parents[2]
DASH = ROOT / "data/processed/dashboard"
RAW = ROOT / "data/raw/cctv_images"
OUT = Path(__file__).parent / "fig"
COLORS = {"car": "#2a78d6", "truck": "#1baf7a", "motorcycle": "#eb6834", "bus": "#8a5cd6", "bicycle": "#d6a72a"}


def camera_map(cams: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    v = cams["rain_effect_pct"].clip(-15, 15)
    sc = ax.scatter(cams.longitude, cams.latitude, c=v, cmap="RdBu_r", vmin=-15, vmax=15,
                    s=18 + cams.mean_calibrated * 2.2, edgecolor="#333", linewidth=0.4)
    cb = fig.colorbar(sc, ax=ax, shrink=0.8)
    cb.set_label("wet vs dry hours, % vs usual")
    ax.set_title("Rain effect per camera (dot size = mean vehicles)")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    fig.tight_layout()
    fig.savefig(OUT / "camera_map.png", dpi=200)
    plt.close(fig)


# Short labels for the cameras named on the weekend map (lowest and highest weekend share).
# Value: (label, x offset, y offset) in points.
WEEKEND_LABELS = {206: ("Narathiwas (Sathorn offices)", 8, -3), 141: ("PTT head office", 6, -12),
                  233: ("Chitralada (government area)", 8, 6), 411: ("Phra Athit (old town)", -10, 10),
                  395: ("Sao Chingcha (old town)", -10, -14), 915: ("Wongwian Yai", -10, -4)}


def weekend_map(cams: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    v = cams["weekend_kept_pct"].clip(40, 100)
    sc = ax.scatter(cams.longitude, cams.latitude, c=v, cmap="RdYlBu", vmin=40, vmax=100,
                    s=18 + cams.mean_calibrated * 2.2, edgecolor="#333", linewidth=0.4)
    cb = fig.colorbar(sc, ax=ax, shrink=0.8)
    cb.set_label("weekend traffic, % of weekday (same hours)")
    for r in cams[cams.camera_id.isin(WEEKEND_LABELS)].itertuples():
        label, dx, dy = WEEKEND_LABELS[r.camera_id]
        ax.annotate(f"{label} {r.weekend_kept_pct:.0f}%", (r.longitude, r.latitude), xytext=(dx, dy),
                    textcoords="offset points", fontsize=7.5, color="#222", ha="left" if dx > 0 else "right",
                    path_effects=[patheffects.withStroke(linewidth=2.5, foreground="white")])
    ax.set_title("How much traffic each camera keeps at the weekend")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    fig.tight_layout()
    fig.savefig(OUT / "weekend_map.png", dpi=200)
    plt.close(fig)


def weekend_by_place(cams: pd.DataFrame) -> None:
    groups = pd.cut(cams["n_mall_market_500m"], [-1, 0, 2, 100], labels=["none", "1–2", "3 or more"])
    g = cams.groupby(groups, observed=True)["weekend_kept_pct"].agg(["mean", "count"])
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    ax.bar(g.index.astype(str), g["mean"], color=[GRID, "#9cc0ea", BLUE], width=0.6)
    for i, (m, n) in enumerate(zip(g["mean"], g["count"])):
        ax.text(i, m + 1.5, f"{m:.0f}%", ha="center", fontsize=11, fontweight="bold")
        ax.text(i, 4, f"{n} cameras", ha="center", fontsize=8.5, color="white" if i == 2 else INK2)
    ax.set_ylim(0, 100)
    ax.set_xlabel("malls / markets within 500 m (OpenStreetMap)")
    ax.set_ylabel("weekend % of weekday")
    ax.set_title("Cameras near shops keep more of their traffic at weekends")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(OUT / "weekend_by_mall.png", dpi=200)
    plt.close(fig)


def hourly_profile(s: pd.DataFrame) -> None:
    g = s.groupby(["daytype", "hour"]).n_calibrated.mean().unstack(0)
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    for col, c in zip(g.columns, [BLUE, ORANGE]):
        ax.plot(g.index, g[col], marker="o", ms=3.5, color=c, label=col)
    ax.set_title("Vehicles per frame by hour (calibrated, all cameras)")
    ax.set_xlabel("hour of day")
    ax.set_ylabel("mean vehicles per frame")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "hourly_profile.png", dpi=200)
    plt.close(fig)


def vehicle_mix(s: pd.DataFrame) -> None:
    tot = s[[f"n_{k}" for k in COLORS]].sum().rename(lambda c: c[2:]).sort_values()
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    ax.barh(tot.index, tot.values / 1e3, color=[COLORS[k] for k in tot.index])
    for i, val in enumerate(tot.values):
        ax.text(val / 1e3 + 5, i, f"{val / tot.sum():.0%}", va="center", fontsize=9, color=INK2)
    ax.set_title("Detected vehicles by class (raw detector, thousands)")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(OUT / "vehicle_mix.png", dpi=200)
    plt.close(fig)


def example_frame(s: pd.DataFrame, det: pd.DataFrame, mask: pd.Series, name: str) -> None:
    pick = s[mask].sort_values("n_vehicles", ascending=False)
    for path in pick.path.head(50):
        if (RAW / path).exists():
            break
    img = Image.open(RAW / path).convert("RGB")
    draw = ImageDraw.Draw(img)
    for r in det[det.path == path].itertuples():
        draw.rectangle([r.x1, r.y1, r.x2, r.y2], outline=COLORS.get(r.vehicle, "white"), width=2)
    img.resize((img.width * 2, img.height * 2), Image.LANCZOS).save(OUT / f"{name}.png")
    print(name, path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cams = pd.read_parquet(DASH / "cameras.parquet")
    s = pd.read_parquet(DASH / "snapshots.parquet")
    det = pd.read_parquet(ROOT / "data/interim/l640/detections.parquet")
    det = det[det.confidence >= 0.25]  # draw only confident boxes so the frame stays readable
    camera_map(cams)
    weekend_map(cams)
    weekend_by_place(cams)
    hourly_profile(s)
    vehicle_mix(s)
    example_frame(s, det, (s.light == "day") & ~s.wet & s.hour.between(9, 11), "frame_dry_day")
    example_frame(s, det, (s.light == "night") & s.wet, "frame_wet_night")


if __name__ == "__main__":
    main()
