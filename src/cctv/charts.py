"""Step 7: report charts for the rain analysis.

Reads the outputs of `cctv.rain` and the hand labels, writes four PNGs:

    rain_levels.png        % vs usual by rain level (95% CI), rain now / 1 h / 2 h before
    wet_dry_by_hour.png    % vs usual by hour of day, wet vs dry hours (95% CI)
    leave_one_day_out.png  the two headline numbers with each day dropped in turn
    detector_error.png     model / hand count by condition: first run, yolo11l 640, calibrated

The calibrated bars in detector_error are cross-fitted: each person's frames are
scaled with factors learned from the other people's frames, so they are not
calibrated against themselves.

    uv run python -m cctv.charts
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from cctv.rain import CLASSES, LEVELS, condition, load  # noqa: E402

INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
NEUTRAL = "#a3a29d"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "axes.titlecolor": INK,
    "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.axisbelow": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "xtick.color": INK2, "ytick.color": INK2, "xtick.labelsize": 9, "ytick.labelsize": 9,
    "font.size": 10, "legend.frameon": False, "legend.fontsize": 9,
})


def _zero_line(ax, axis: str = "y") -> None:
    (ax.axhline if axis == "y" else ax.axvline)(0, color=INK2, linewidth=1, zorder=1)


def _cluster_boot(df: pd.DataFrame, by: str, col: str, n_boot: int, seed: int = 0) -> pd.DataFrame:
    """Mean of col per group with 95% CI from resampling camera-days."""
    cluster = df["camera_id"].astype(str) + "_" + df["timestamp"].dt.date.astype(str)
    sums = df.groupby([cluster, by], observed=True)[col].sum()
    sizes = df.groupby([cluster, by], observed=True).size()
    clusters = cluster.unique()
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        pick = pd.Series(rng.choice(clusters, size=len(clusters))).value_counts()
        w = pick.reindex(sums.index.get_level_values(0)).fillna(0).to_numpy()
        draws.append((sums * w).groupby(level=1).sum() / (sizes * w).groupby(level=1).sum())
    draws = pd.concat(draws, axis=1)
    pct = lambda x: 100 * np.expm1(x)  # noqa: E731
    return pd.DataFrame({"pct": pct(df.groupby(by, observed=True)[col].mean()),
                         "lo": pct(draws.quantile(0.025, axis=1)),
                         "hi": pct(draws.quantile(0.975, axis=1)),
                         "n": df.groupby(by, observed=True).size()})


def rain_levels(effect: pd.DataFrame, out: Path) -> None:
    timings = [("rain_now", "Rain in the same hour"), ("rain_before", "Rain 1 h before"),
               ("rain_2h_before", "Rain 2 h before")]
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.8), sharey=True)
    x = np.arange(len(LEVELS))
    for ax, (timing, title) in zip(axes, timings):
        t = effect[effect["timing"] == timing].set_index("rain").loc[LEVELS]
        colors = [NEUTRAL, BLUE, BLUE, BLUE]
        ax.bar(x, t["calibrated_%"], width=0.6, color=colors, zorder=2)
        ax.errorbar(x, t["calibrated_%"], yerr=[t["calibrated_%"] - t["calibrated_lo"],
                                                 t["calibrated_hi"] - t["calibrated_%"]],
                    fmt="none", ecolor=INK, elinewidth=1.2, capsize=3, zorder=3)
        _zero_line(ax)
        ax.set_title(title)
        names = ["dry", "light\n0.1–2", "moderate\n2–5", "heavy\n>5"]
        ax.set_xticks(x, [f"{nm}\nn={n:,}" for nm, n in zip(names, t["snapshots"])], fontsize=8)
        ax.grid(axis="x", visible=False)
        for xi, (v, lo, hi) in enumerate(zip(t["calibrated_%"], t["calibrated_lo"], t["calibrated_hi"])):
            up = v >= 0
            ax.annotate(f"{v:+.1f}%", (xi, hi if up else lo), xytext=(0, 3 if up else -3),
                        textcoords="offset points", ha="center", va="bottom" if up else "top",
                        fontsize=8.5, color=INK)
        ax.set_ylim(-11, 11)
    axes[0].set_ylabel("vehicles vs usual for that camera & hour (%)")
    fig.suptitle("Heavy rain lines up with more vehicles in the same hour, not later",
                 x=0.01, ha="left", fontsize=12, fontweight="bold", color=INK)
    fig.text(0.01, 0.005, "Calibrated vehicle count, rain in mm/h (Open-Meteo). Bars: mean; "
             "whiskers: 95% CI from resampling camera-days. 7 days, 25–31 Aug 2026.",
             fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(out, dpi=200)
    plt.close(fig)


def wet_dry_by_hour(snaps: pd.DataFrame, out: Path, n_boot: int) -> None:
    fig, ax = plt.subplots(figsize=(8, 4))
    for wet, color, name in [(False, NEUTRAL, "dry hours"), (True, BLUE, "wet hours (>0.1 mm/h)")]:
        t = _cluster_boot(snaps[snaps["wet"] == wet], "hour", "excess_calibrated", n_boot)
        t = t[t["n"] >= 100]
        ax.fill_between(t.index, t["lo"], t["hi"], color=color, alpha=0.18, linewidth=0, zorder=2)
        ax.plot(t.index, t["pct"], color=color, linewidth=2, marker="o", markersize=4, zorder=3, label=name)
        ax.annotate(name, (t.index[-1], t["pct"].iloc[-1]), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=9, color=INK)
    _zero_line(ax)
    ax.set_xlabel("hour of day")
    ax.set_ylabel("vehicles vs usual (%)")
    ax.set_xticks(range(6, 22, 2))
    ax.legend(loc="upper left")
    ax.set_title("Wet vs dry by hour of day")
    ax.margins(x=0.02)
    ax.set_xlim(right=ax.get_xlim()[1] + 2.5)
    fig.text(0.01, 0.005, "Calibrated count vs the same camera, hour and day type. Bands: 95% CI "
             "(camera-day bootstrap). Hours with <100 snapshots hidden.", fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=200)
    plt.close(fig)


def leave_one_day_out(snaps: pd.DataFrame, out: Path) -> pd.DataFrame:
    snaps = snaps.assign(date=snaps["timestamp"].dt.date)
    rows = []
    for drop in [None, *sorted(snaps["date"].unique())]:
        d = snaps if drop is None else snaps[snaps["date"] != drop]
        e, wet, late = d["excess_calibrated"], d["wet"], d["hour"] >= 17
        rows.append({
            "dropped": "none (all 7 days)" if drop is None else pd.Timestamp(drop).strftime("%a %d %b"),
            "heavy": 100 * (np.expm1(e[d["rain_now"] > 5].mean()) - np.expm1(e[~wet].mean())),
            "evening": 100 * (np.expm1(e[late & wet].mean()) - np.expm1(e[late & ~wet].mean())),
        })
    t = pd.DataFrame(rows)
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.8), sharey=True)
    y = np.arange(len(t))[::-1]
    for ax, col, title in [(axes[0], "heavy", "Heavy rain (>5 mm/h) minus dry"),
                           (axes[1], "evening", "Evening (17–21) wet minus dry")]:
        ax.hlines(y, 0, t[col], color=GRID, linewidth=2, zorder=2)
        colors = [INK] + [BLUE] * (len(t) - 1)
        ax.scatter(t[col], y, s=48, color=colors, zorder=3, edgecolor=SURFACE, linewidth=1.5)
        for yi, v in zip(y, t[col]):
            ax.annotate(f"{v:+.1f}", (v, yi), xytext=(7 if v >= 0 else -7, 0), textcoords="offset points",
                        ha="left" if v >= 0 else "right", va="center", fontsize=8.5, color=INK)
        _zero_line(ax, "x")
        ax.set_title(title)
        ax.set_xlabel("percentage points")
        ax.grid(axis="y", visible=False)
        lo, hi = ax.get_xlim()
        ax.set_xlim(min(lo, -1) - 1.5, hi + 1.5)
    axes[0].set_yticks(y, ["all 7 days"] + [f"without {d}" for d in t["dropped"][1:]])
    fig.suptitle("Leave one day out: the heavy-rain effect holds; the evening dip is one day",
                 x=0.01, ha="left", fontsize=12, fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return t


def _factors(lab: pd.DataFrame) -> dict[str, pd.Series]:
    out = {}
    for name, cols in CLASSES.items():
        hand = lab[cols].sum(axis=1).groupby(lab["cond"]).sum()
        model = lab[[f"n_{c}" for c in cols]].sum(axis=1).groupby(lab["cond"]).sum()
        out[name] = (hand / model.where(model > 0)).fillna(1.0)
    return out


def detector_error(images: Path, counts: Path, first_counts: Path, weather: Path,
                   labels: Path, out: Path) -> pd.DataFrame:
    df = load(images, counts, weather)
    lab = pd.read_csv(labels / "export.csv").merge(
        pd.read_csv(labels / "assignments.csv")[["who", "path", "role"]], on=["who", "path"])
    lab = lab[(lab["role"] == "own") & (lab["unusable"] == 0)]
    model_cols = [f"n_{c}" for cs in CLASSES.values() for c in cs]
    lab = lab.merge(df[["path", "hour", "rain_now"] + model_cols], on="path")
    lab["cond"] = condition(lab["hour"], lab["rain_now"])
    first = pd.read_parquet(first_counts, columns=["path", "n_vehicles"]).rename(columns={"n_vehicles": "first"})
    lab = lab.merge(first, on="path", how="left")

    hand_cols = [c for cs in CLASSES.values() for c in cs]
    lab["hand"] = lab[hand_cols].sum(axis=1)
    lab["l640"] = lab[model_cols].sum(axis=1)
    lab["calibrated"] = 0.0
    for who in lab["who"].unique():  # cross-fit: factors from everyone else's frames
        mine = lab["who"] == who
        f = _factors(lab[~mine])
        for name, cols in CLASSES.items():
            lab.loc[mine, "calibrated"] += (lab.loc[mine, [f"n_{c}" for c in cols]].sum(axis=1)
                                            * lab.loc[mine, "cond"].map(f[name]).fillna(1.0))

    order = [f"{p} {w}" for p in ["day 6-16", "evening 17-19", "late 20-21"] for w in ["dry", "wet"]]
    g = lab.groupby("cond")
    t = pd.DataFrame({k: g[k].sum() / g["hand"].sum() for k in ["first", "l640", "calibrated"]})
    t["frames"] = g.size()
    t = t.reindex(order)
    overall = lab[["first", "l640", "calibrated"]].sum() / lab["hand"].sum()
    t.loc["all frames"] = [*overall, len(lab)]

    fig, ax = plt.subplots(figsize=(9, 4.4))
    x = np.arange(len(t))
    series = [("first", NEUTRAL, "first run: yolo11s, conf 0.25"),
              ("l640", BLUE, "yolo11l, 640 px, conf 0.05"),
              ("calibrated", AQUA, "yolo11l + per-condition calibration (cross-fitted)")]
    w, top = 0.26, 1.3
    for i, (col, color, name) in enumerate(series):
        xs = x + (i - 1) * (w + 0.02)
        ax.bar(xs, t[col].clip(upper=top), width=w, color=color, label=name, zorder=2)
        for xi, v in zip(xs, t[col]):
            label = f"{v:.2f}" if v <= top else f"{v:.2f}↑"
            ax.text(xi, min(v, top) + 0.02, label, ha="center", va="bottom", fontsize=7, color=INK)
    ax.axhline(1, color=INK, linewidth=1, linestyle=(0, (4, 3)), zorder=1)
    ax.text(-0.95, 1.02, "hand count", ha="left", va="bottom", fontsize=8, color=INK2)
    ax.set_xlim(-1, len(t) - 0.5)
    ax.set_xticks(x, [c.replace(" ", "\n", 1).replace("-", "–") + f"\n{int(n)} frames"
                      for c, n in zip(t.index, t["frames"])], fontsize=8)
    ax.set_ylabel("vehicles found / vehicles counted by hand")
    ax.set_ylim(0, 1.45)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="lower left", ncols=3, fontsize=8, bbox_to_anchor=(0, 1.0), borderaxespad=0.3)
    ax.set_title("Detector undercount, before and after", pad=24)
    fig.text(0.01, 0.005, "Team hand counts on own (non-overlap) usable frames. Wet = >0.1 mm/h in the hour.\n"
             "Late wet: the motorcycle factor rests on 16 model detections, so cross-fitting overshoots.",
             fontsize=7.5, color=INK2)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return t


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--processed", type=Path, default=Path("data/processed/l640"))
    parser.add_argument("--images", type=Path, default=Path("data/interim/images.parquet"))
    parser.add_argument("--counts", type=Path, default=Path("data/interim/l640/image_counts.parquet"))
    parser.add_argument("--first-counts", type=Path, default=Path("data/interim/image_counts.parquet"))
    parser.add_argument("--weather", type=Path, default=Path("data/interim/weather.parquet"))
    parser.add_argument("--labels", type=Path, default=Path("data/labels"))
    parser.add_argument("--out", type=Path, default=Path("reports/figures"))
    parser.add_argument("--boot", type=int, default=300)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    effect = pd.read_csv(args.processed / "rain_effect.csv")
    snaps = pd.read_parquet(args.processed / "rain_snapshots.parquet")
    pd.set_option("display.float_format", "{:.2f}".format)

    rain_levels(effect, args.out / "rain_levels.png")
    wet_dry_by_hour(snaps, args.out / "wet_dry_by_hour.png", args.boot)
    print(leave_one_day_out(snaps, args.out / "leave_one_day_out.png").to_string(index=False))
    print(detector_error(args.images, args.counts, args.first_counts, args.weather, args.labels,
                         args.out / "detector_error.png").to_string())
    print(f"wrote 4 charts to {args.out}")


if __name__ == "__main__":
    main()
