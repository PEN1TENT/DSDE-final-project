"""Step 3b: local page for counting vehicles by hand in the sampled frames.

Model boxes are never shown, so the hand counts stay independent of the model.
Each save is written to labels.csv at once; close and reopen any time.

    uv run python -m cctv.label_server        # then open http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import csv
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import pandas as pd

CLASSES = ["car", "motorcycle", "bus", "truck", "bicycle"]
FIELDS = ["path", *CLASSES, "unusable", "note"]
PAGE = Path(__file__).with_name("label_page.html")


class Store:
    def __init__(self, sample: Path, labels: Path):
        self.items = pd.read_csv(sample)["path"].tolist()
        self.allowed = set(self.items)
        self.path = labels
        self.labels: dict[str, dict] = {}
        if labels.exists():
            with labels.open(newline="", encoding="utf-8") as f:
                self.labels = {row["path"]: row for row in csv.DictReader(f)}

    def save(self, row: dict) -> None:
        clean = {"path": row["path"], "note": str(row.get("note", "")).strip()}
        clean.update({c: max(0, int(row.get(c) or 0)) for c in CLASSES})
        clean["unusable"] = int(bool(row.get("unusable")))
        self.labels[clean["path"]] = clean
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(self.labels[p] for p in self.items if p in self.labels)
        tmp.replace(self.path)  # never leave a half-written file


def make_handler(store: Store, raw: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet
            pass

        def _send(self, body: bytes, kind: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/items":
                data = {"classes": CLASSES, "items": store.items, "labels": store.labels}
                self._send(json.dumps(data, ensure_ascii=False).encode(), "application/json")
            elif self.path.startswith("/img/"):
                rel = unquote(self.path[len("/img/") :])
                if rel not in store.allowed:  # only sampled frames; blocks ../ tricks
                    return self._send(b"not found", "text/plain", 404)
                self._send((raw / rel).read_bytes(), "image/jpeg")
            else:
                self._send(b"not found", "text/plain", 404)

        def do_POST(self):
            if self.path != "/api/label":
                return self._send(b"not found", "text/plain", 404)
            row = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if row.get("path") not in store.allowed:
                return self._send(b"unknown frame", "text/plain", 400)
            store.save(row)
            self._send(json.dumps({"labelled": len(store.labels)}).encode(), "application/json")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, default=Path("data/raw/cctv_images"))
    parser.add_argument("--sample", type=Path, default=Path("data/labels/sample.csv"))
    parser.add_argument("--labels", type=Path, default=Path("data/labels/labels.csv"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    store = Store(args.sample, args.labels)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(store, args.raw))
    print(f"{len(store.labels)}/{len(store.items)} labelled. Open http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    server.serve_forever()


if __name__ == "__main__":
    main()
