"""Step 3b: split the label sample between labellers and build the homelab bundle.

Each person gets an equal share of the sample, plus `--overlap` frames from the
next person's share. Those overlap frames are counted twice, which measures how
much two humans disagree.

Writes:
  data/labels/assignments.csv   who labels which frame (tracked in git)
  data/labels/tokens.csv        one secret key per person + admin (NOT in git)
  deploy/build/                 folder to copy to the homelab (see README)

Re-running keeps existing keys, so links already sent stay valid.

    uv run python -m cctv.assign --people alice,bob,carol,dave,erin
"""

from __future__ import annotations

import argparse
import csv
import secrets
import shutil
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent


def make_assignments(sample: pd.DataFrame, people: list[str], overlap: int, seed: int) -> pd.DataFrame:
    paths = sample["path"].tolist()  # already shuffled by labelset, so shards are balanced
    shards = {who: paths[i :: len(people)] for i, who in enumerate(people)}
    rows = []
    for i, who in enumerate(people):
        neighbour = shards[people[(i + 1) % len(people)]]
        rows += [{"who": who, "path": p, "role": "own"} for p in shards[who]]
        rows += [{"who": who, "path": p, "role": "overlap"} for p in neighbour[:overlap]]
    frame = pd.DataFrame(rows)
    # Mix overlap frames in with own frames so nobody knows which ones are double-counted.
    frame = frame.sample(frac=1, random_state=seed)
    frame["order"] = frame.groupby("who").cumcount()
    return frame.sort_values(["who", "order"]).reset_index(drop=True)


def load_tokens(path: Path, names: list[str]) -> dict[str, str]:
    tokens = {}
    if path.exists():
        with path.open(newline="") as f:
            tokens = {row["who"]: row["key"] for row in csv.DictReader(f)}
    for who in names:
        tokens.setdefault(who, secrets.token_urlsafe(12))
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["who", "key"])
        writer.writerows(sorted(tokens.items()))
    return tokens


def build_bundle(out: Path, raw: Path, labels_dir: Path, deploy: Path) -> int:
    """Everything the homelab needs: app, sampled images, assignments, keys, tailscale config."""
    (out / "app").mkdir(parents=True, exist_ok=True)
    (out / "data" / "labels").mkdir(parents=True, exist_ok=True)
    (out / "tailscale").mkdir(parents=True, exist_ok=True)
    for name in ("label_server.py", "label_page.html"):
        shutil.copy2(HERE / name, out / "app" / name)
    for name in ("assignments.csv", "tokens.csv"):
        shutil.copy2(labels_dir / name, out / "data" / name)
    shutil.copy2(deploy / "serve.json", out / "tailscale" / "serve.json")
    shutil.copy2(deploy / "docker-compose.yml", out / "docker-compose.yml")

    paths = pd.read_csv(labels_dir / "assignments.csv")["path"].unique()
    for rel in paths:
        target = out / "data" / "images" / rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(raw / rel, target)
    return len(paths)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--people", required=True, help="comma-separated names, used in links and file names")
    parser.add_argument("--overlap", type=int, default=40, help="frames each person also labels from a neighbour")
    parser.add_argument("--labels", type=Path, default=Path("data/labels"))
    parser.add_argument("--raw", type=Path, default=Path("data/raw/cctv_images"))
    parser.add_argument("--deploy", type=Path, default=Path("deploy"))
    parser.add_argument("--url", default="https://cctv-label.<your-tailnet>.ts.net", help="public URL, for the printed links")
    parser.add_argument("--seed", type=int, default=403)
    args = parser.parse_args()

    people = [p.strip().lower() for p in args.people.split(",") if p.strip()]
    if len(set(people)) != len(people) or not all(p.isalnum() for p in people) or "admin" in people:
        parser.error("names must be unique, letters/digits only, and not 'admin'")

    sample = pd.read_csv(args.labels / "sample.csv")
    assignments = make_assignments(sample, people, args.overlap, args.seed)
    assignments.to_csv(args.labels / "assignments.csv", index=False)
    tokens = load_tokens(args.labels / "tokens.csv", [*people, "admin"])
    n_images = build_bundle(args.deploy / "build", args.raw, args.labels, args.deploy)

    print(assignments.groupby(["who", "role"]).size().unstack().to_string())
    print(f"\n{n_images} images bundled in {args.deploy / 'build'}\n\nLinks (send each person only their own):")
    for who in people:
        print(f"  {who:>8}: {args.url}/?who={who}&key={tokens[who]}")
    print(f"\n   admin: {args.url}/admin?key={tokens['admin']}")


if __name__ == "__main__":
    main()
