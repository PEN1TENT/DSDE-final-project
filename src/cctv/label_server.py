"""Labelling server for the team: each person counts vehicles in their own frames.

Standard library only, so it runs in a stock `python` container with nothing to
install. Model boxes are never shown, so hand counts stay independent of the model.

Data folder layout (built by `python -m cctv.assign`):
  images/<camera_id>/<file>.jpg   the sampled frames only
  assignments.csv                 who, path, role, order
  tokens.csv                      who, key   (one secret per person, plus "admin")
  labels/labels_<who>.csv         written here on every save

    python label_server.py --data deploy/build/data            # local test
    open http://127.0.0.1:8765/?who=<name>&key=<key>
"""

from __future__ import annotations

import argparse
import csv
import hmac
import html
import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

CLASSES = ["car", "motorcycle", "bus", "truck", "bicycle"]
FIELDS = ["path", *CLASSES, "unusable", "note", "saved_at"]
PAGE = Path(__file__).with_name("label_page.html")


class Store:
    def __init__(self, data: Path):
        self.data = data
        self.labels_dir = data / "labels"
        self.labels_dir.mkdir(parents=True, exist_ok=True)
        with (data / "tokens.csv").open(newline="") as f:
            self.tokens = {row["who"]: row["key"] for row in csv.DictReader(f)}
        self.items: dict[str, list[str]] = {}
        with (data / "assignments.csv").open(newline="") as f:
            for row in sorted(csv.DictReader(f), key=lambda r: (r["who"], int(r["order"]))):
                self.items.setdefault(row["who"], []).append(row["path"])
        self.allowed = {who: set(paths) for who, paths in self.items.items()}
        self.labels = {who: self._load(who) for who in self.items}
        self.lock = threading.Lock()

    def _file(self, who: str) -> Path:
        return self.labels_dir / f"labels_{who}.csv"

    def _load(self, who: str) -> dict[str, dict]:
        path = self._file(who)
        if not path.exists():
            return {}
        with path.open(newline="", encoding="utf-8") as f:
            return {row["path"]: row for row in csv.DictReader(f)}

    def check(self, who: str | None, key: str | None) -> bool:
        expected = self.tokens.get(who or "")
        return bool(expected and key) and hmac.compare_digest(expected, key)

    def save(self, who: str, row: dict) -> int:
        clean = {"path": row["path"], "note": str(row.get("note", "")).strip()[:500]}
        clean.update({c: max(0, min(500, int(row.get(c) or 0))) for c in CLASSES})
        clean["unusable"] = int(bool(row.get("unusable")))
        clean["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.lock:
            labels = self.labels[who]
            labels[clean["path"]] = clean
            tmp = self._file(who).with_suffix(".tmp")
            with tmp.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(labels[p] for p in self.items[who] if p in labels)
            tmp.replace(self._file(who))  # never leave a half-written file
            return len(labels)


def admin_page(store: Store, key: str) -> bytes:
    rows = []
    for who, paths in sorted(store.items.items()):
        labels = store.labels[who]
        last = max((r.get("saved_at", "") for r in labels.values()), default="")
        pct = 100 * len(labels) / len(paths)
        rows.append(
            f"<tr><td>{html.escape(who)}</td><td>{len(labels)} / {len(paths)}</td>"
            f"<td><div class=bar><div style='width:{pct:.0f}%'></div></div></td><td>{html.escape(last[:16].replace('T', ' '))}</td></tr>"
        )
    done = sum(len(v) for v in store.labels.values())
    total = sum(len(v) for v in store.items.values())
    return f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Labelling Progress</title><meta http-equiv=refresh content=30><style>
:root{{--bg:#f6f6f4;--ink:#1d1d1b;--line:#deddd8;--ok:#1a7f37}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--ink:#ecebe6;--line:#33332f;--ok:#3fb950}}}}
body{{background:var(--bg);color:var(--ink);font:14px system-ui,sans-serif;max-width:720px;margin:0 auto;padding:16px}}
table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:8px;border-bottom:1px solid var(--line)}}
.bar{{height:8px;background:var(--line);border-radius:4px;overflow:hidden;min-width:80px}}.bar div{{height:100%;background:var(--ok)}}
a{{color:inherit}}</style></head><body>
<h1>Labelling Progress</h1><p>{done} / {total} labels saved. Refreshes every 30 s.</p>
<table><tr><th>Who</th><th>Done</th><th></th><th>Last save (UTC)</th></tr>{''.join(rows)}</table>
<p><a href="/admin/export.csv?key={html.escape(key)}">Download all labels (CSV)</a></p></body></html>""".encode()


def export_csv(store: Store) -> bytes:
    lines = [",".join(["who", *FIELDS])]
    for who in sorted(store.labels):
        for row in store.labels[who].values():
            cells = [who, *(str(row.get(f, "")) for f in FIELDS)]
            lines.append(",".join('"' + c.replace('"', '""') + '"' for c in cells))
    return ("\n".join(lines) + "\n").encode("utf-8")


def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep container logs quiet
            pass

        def _send(self, body: bytes, kind: str, status: int = 200, cache: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=86400" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _deny(self) -> None:
            self._send(b"Link is missing or wrong. Ask the project owner for your personal link.", "text/plain; charset=utf-8", 403)

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            who, key = q.get("who"), q.get("key")
            if url.path == "/":
                self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/items":
                if not store.check(who, key) or who == "admin":
                    return self._deny()
                data = {"who": who, "classes": CLASSES, "items": store.items[who], "labels": store.labels[who]}
                self._send(json.dumps(data, ensure_ascii=False).encode(), "application/json")
            elif url.path.startswith("/img/"):
                rel = unquote(url.path[len("/img/") :])
                if not store.check(who, key) or rel not in store.allowed.get(who, ()):  # blocks ../ tricks too
                    return self._deny()
                self._send((store.data / "images" / rel).read_bytes(), "image/jpeg", cache=True)
            elif url.path == "/admin":
                if not store.check("admin", key):
                    return self._deny()
                self._send(admin_page(store, key), "text/html; charset=utf-8")
            elif url.path == "/admin/export.csv":
                if not store.check("admin", key):
                    return self._deny()
                self._send(export_csv(store), "text/csv; charset=utf-8")
            else:
                self._send(b"not found", "text/plain", 404)

        def do_POST(self):
            if self.path != "/api/label":
                return self._send(b"not found", "text/plain", 404)
            length = int(self.headers.get("Content-Length") or 0)
            if length > 10_000:
                return self._send(b"too large", "text/plain", 413)
            row = json.loads(self.rfile.read(length) or b"{}")
            who = row.get("who")
            if not store.check(who, row.get("key")) or who == "admin":
                return self._deny()
            if row.get("path") not in store.allowed[who]:
                return self._send(b"unknown frame", "text/plain", 400)
            done = store.save(who, row)
            self._send(json.dumps({"labelled": done}).encode(), "application/json")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=Path(os.environ.get("LABEL_DATA", "/data")))
    parser.add_argument("--host", default=os.environ.get("LABEL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LABEL_PORT", "8765")))
    args = parser.parse_args()

    store = Store(args.data)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store))
    for who, paths in sorted(store.items.items()):
        print(f"{who}: {len(store.labels[who])}/{len(paths)} labelled", flush=True)
    print(f"listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
