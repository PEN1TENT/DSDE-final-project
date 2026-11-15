"""Run the whole pipeline in order, skipping steps whose outputs are newer than their inputs.

Steps (each is also a module you can run on its own):

  inventory  images -> data/interim/images.parquet
  detect     YOLO11-L @640 -> data/interim/l640/image_counts.parquet   (slow; resumes)
  weather    Open-Meteo rain -> data/interim/weather.parquet
  osm        OpenStreetMap road context -> data/interim/osm_context.parquet
  daylight   sunrise-sunset.org -> data/interim/daylight.parquet
  rain       rain vs congestion -> data/processed/l640/
  charts     report figures -> reports/figures/
  mart       dashboard tables -> data/processed/dashboard/

    uv run python -m cctv.pipeline                 # whatever is out of date
    uv run python -m cctv.pipeline --only rain mart
    uv run python -m cctv.pipeline --force --from rain
    uv run python -m cctv.pipeline --dry-run

The golden-set labelling (labelset / assign / evaluate) involves people, so it is not here;
its output, data/labels/export.csv, is an input to the rain step.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

RAW = "data/raw/cctv_images"


@dataclass
class Step:
    name: str
    args: list[str]
    inputs: list[str]
    outputs: list[str]
    extra: list[str] = field(default_factory=list)


STEPS = [
    Step("inventory", ["cctv.inventory", "--raw", RAW], [RAW], ["data/interim/images.parquet"]),
    Step("detect", ["cctv.detect", "--raw", RAW, "--model", "yolo11l.pt", "--imgsz", "640", "--out", "data/interim/l640",
                    "--inventory", "data/interim/images.parquet"],
         ["data/interim/images.parquet"], ["data/interim/l640/image_counts.parquet"]),
    Step("weather", ["cctv.weather"], ["data/raw/cctv_info.csv", "data/interim/images.parquet"],
         ["data/interim/weather.parquet"]),
    Step("osm", ["cctv.osm"], ["data/raw/cctv_info.csv"], ["data/interim/osm_context.parquet"]),
    Step("daylight", ["cctv.daylight"], ["data/raw/cctv_info.csv", "data/interim/images.parquet"],
         ["data/interim/daylight.parquet"]),
    Step("rain", ["cctv.rain", "--counts", "data/interim/l640/image_counts.parquet", "--out", "data/processed/l640"],
         ["data/interim/l640/image_counts.parquet", "data/interim/weather.parquet", "data/labels/export.csv"],
         ["data/processed/l640/rain_snapshots.parquet", "data/processed/l640/rain_effect.csv"]),
    Step("charts", ["cctv.charts"], ["data/processed/l640/rain_snapshots.parquet"], ["reports/figures/rain_levels.png"]),
    Step("mart", ["cctv.mart"],
         ["data/processed/l640/rain_snapshots.parquet", "data/interim/osm_context.parquet",
          "data/interim/daylight.parquet", "data/raw/cctv_info.csv"],
         ["data/processed/dashboard/snapshots.parquet", "data/processed/dashboard/cameras.parquet"]),
]


def mtime(path: str) -> float | None:
    p = Path(path)
    # For the image folder this is the folder's own mtime, which changes when cameras are added.
    return p.stat().st_mtime if p.exists() else None


def stale(step: Step) -> str | None:
    """Why the step must run, or None if it is up to date."""
    outs = [mtime(o) for o in step.outputs]
    if any(t is None for t in outs):
        return "output missing"
    ins = [t for t in (mtime(i) for i in step.inputs) if t is not None]
    if ins and max(ins) > min(outs):
        return "input changed"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    names = [s.name for s in STEPS]
    parser.add_argument("--only", nargs="+", choices=names, help="run just these steps")
    parser.add_argument("--from", dest="start", choices=names, help="start at this step")
    parser.add_argument("--force", action="store_true", help="run selected steps even if up to date")
    parser.add_argument("--dry-run", action="store_true", help="print what would run")
    parser.add_argument("--device", default=None, help="passed to detect, e.g. mps or cuda")
    args = parser.parse_args()

    steps = STEPS[names.index(args.start):] if args.start else STEPS
    if args.only:
        steps = [s for s in steps if s.name in args.only]
    for step in steps:
        reason = "forced" if args.force else stale(step)
        if reason is None:
            print(f"[skip] {step.name}: up to date")
            continue
        cmd = [sys.executable, "-m", *step.args]
        if step.name == "detect" and args.device:
            cmd += ["--device", args.device]
        print(f"[run ] {step.name}: {reason}\n       {' '.join(cmd[1:])}", flush=True)
        if not args.dry_run:
            result = subprocess.run(cmd)
            if result.returncode != 0:
                sys.exit(f"step {step.name} failed with exit code {result.returncode}")


if __name__ == "__main__":
    main()
