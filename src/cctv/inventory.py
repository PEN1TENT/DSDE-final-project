"""Step 1: build one row per image with camera, timestamp and quality metrics.

Expected layout: <raw>/<camera_id>/<image>. The camera id is the name of the
folder that directly contains the image.

    uv run python -m cctv.inventory --raw data/raw --out data/interim
"""

from __future__ import annotations

import argparse
import hashlib
import re
import struct
import zlib
from pathlib import Path
from typing import Any

try:
    import cv2
    import numpy as np
    import pandas as pd
except ImportError:  # Allow pure-stdlib unit testing of container/QC helpers.
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    pd = None  # type: ignore[assignment]

try:
    from cctv import timestamps
except ImportError:  # `timestamps` imports PIL, which may not be installed in stdlib-only envs.
    timestamps = None  # type: ignore[assignment]

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"
PNG_SIG = b"\x89PNG\r\n\x1a\n"
PNG_IEND = b"\x49\x45\x4e\x44\xae\x42\x60\x82"
WHITE_PNG_MD5 = "d4bf31b19261c16f22c17224fab0df3f"
GST_BARS_MD5 = "4a6d31be2e3b9feafae84b191169d708"
_HTML_TAIL_RE = re.compile(rb"(?:\r\n|\n)*<!DOCTYPE\s+html", re.IGNORECASE)
_TAIL_ACTION_RE = re.compile(rb'show\.aspx\?image=\d+', re.IGNORECASE)


def strip_html_tail(data: bytes) -> tuple[bytes, bytes, str]:
    """Strip any appended HTML payload after JPEG EOI or PNG IEND.

    Returns `(core_bytes, tail_bytes, container)` where `container` is one of
    `'jpeg'`, `'png'`, `'truncated_jpeg'`, `'truncated_png'`, or `'unknown'`.
    """
    html_match = _HTML_TAIL_RE.search(data)
    html_pos = html_match.start() if html_match else -1

    if data.startswith(PNG_SIG):
        limit = html_pos if html_pos != -1 else len(data)
        iend_pos = data.find(PNG_IEND, 0, limit)
        if iend_pos != -1:
            end = iend_pos + len(PNG_IEND)
            return data[:end], data[end:], "png"
        if html_pos != -1:
            return data[:html_pos], data[html_pos:], "truncated_png"
        return data, b"", "truncated_png"

    if data.startswith(JPEG_SOI):
        limit = html_pos if html_pos != -1 else len(data)
        eoi_pos = data.rfind(JPEG_EOI, 0, limit)
        if eoi_pos != -1:
            end = eoi_pos + len(JPEG_EOI)
            return data[:end], data[end:], "jpeg"
        if html_pos != -1:
            return data[:html_pos], data[html_pos:], "truncated_jpeg"
        return data, b"", "truncated_jpeg"

    if html_pos != -1:
        return data[:html_pos], data[html_pos:], "unknown"
    return data, b"", "unknown"


def _is_solid_white_png(core: bytes) -> bool:
    """Return True if PNG bytes represent a solid white (all-255) 8-bit image."""
    if not core.startswith(PNG_SIG):
        return False
    pos = len(PNG_SIG)
    n = len(core)
    width = height = bit_depth = color_type = None
    idat_parts: list[bytes] = []
    while pos + 8 <= n:
        chunk_len = struct.unpack(">I", core[pos:pos + 4])[0]
        chunk_type = core[pos + 4:pos + 8]
        d_start = pos + 8
        d_end = d_start + chunk_len
        if d_end + 4 > n:
            break
        chunk_data = core[d_start:d_end]
        if chunk_type == b"IHDR" and len(chunk_data) >= 13:
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk_data[:10])
        elif chunk_type == b"IDAT":
            idat_parts.append(chunk_data)
        elif chunk_type == b"IEND":
            break
        pos = d_end + 4

    if not (width and height and bit_depth == 8 and color_type in (0, 2, 6) and idat_parts):
        return False
    bpp = {0: 1, 2: 3, 6: 4}[color_type]
    stride = width * bpp
    try:
        raw = zlib.decompress(b"".join(idat_parts))
    except zlib.error:
        return False
    if len(raw) != height * (1 + stride):
        return False

    prev = bytearray(stride)
    for row_idx in range(height):
        start = row_idx * (1 + stride)
        flt = raw[start]
        scan = raw[start + 1:start + 1 + stride]
        cur = bytearray(stride)
        if flt == 0:
            cur[:] = scan
        elif flt == 1:
            for i in range(stride):
                cur[i] = (scan[i] + (cur[i - bpp] if i >= bpp else 0)) & 0xFF
        elif flt == 2:
            for i in range(stride):
                cur[i] = (scan[i] + prev[i]) & 0xFF
        elif flt == 3:
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                cur[i] = (scan[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif flt == 4:
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                up = prev[i]
                up_left = prev[i - bpp] if i >= bpp else 0
                p = left + up - up_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
                pred = left if (pa <= pb and pa <= pc) else (up if pb <= pc else up_left)
                cur[i] = (scan[i] + pred) & 0xFF
        else:
            return False
        if any(b != 255 for b in cur):
            return False
        prev = cur
    return True


def inspect_image_bytes(data: bytes) -> dict[str, Any]:
    """Pure-stdlib container, stripped-MD5, and anomaly flags for raw image bytes."""
    core, tail, container = strip_html_tail(data)
    core_md5 = hashlib.md5(core).hexdigest()
    full_md5 = hashlib.md5(data).hexdigest()
    white_png = container == "png" and (core_md5 == WHITE_PNG_MD5 or _is_solid_white_png(core))
    truncated_jpeg = container == "truncated_jpeg"
    gst_bars = container == "jpeg" and core_md5 == GST_BARS_MD5
    placeholder = white_png or truncated_jpeg or gst_bars
    return {
        "bytes": len(data),
        "md5": full_md5,
        "core_md5": core_md5,
        "container": container,
        "has_html_tail": bool(tail and (_HTML_TAIL_RE.search(tail) or _TAIL_ACTION_RE.search(tail))),
        "white_png": white_png,
        "truncated_jpeg": truncated_jpeg,
        "gst_bars": gst_bars,
        "placeholder": placeholder,
    }


def compute_frozen_flags(
    records: list[dict[str, Any]],
    *,
    bridge_png: bool = True,
) -> list[dict[str, Any]]:
    """Compute `frozen_strict`, `frozen_bridged`, and `frozen` on sorted per-camera rows.

    Frozen detection compares `core_md5` across valid non-placeholder frames only
    (skipping `white_png`, `truncated_jpeg`, and `gst_bars`). When `bridge_png`
    is True, an intervening `white_png` or `truncated_jpeg` does not break an
    ongoing frozen streak.
    """
    out = [dict(r) for r in records]
    last_valid_md5: str | None = None
    prev_was_valid = False
    prev_valid_md5: str | None = None

    for row in out:
        is_placeholder = bool(
            row.get("placeholder")
            or row.get("white_png")
            or row.get("truncated_jpeg")
            or row.get("gst_bars")
        )
        core_md5 = row.get("core_md5") or row.get("md5")
        if is_placeholder or not core_md5:
            row["frozen_strict"] = False
            row["frozen_bridged"] = False
            row["frozen"] = False
            prev_was_valid = False
            prev_valid_md5 = None
            continue

        strict = bool(prev_was_valid and core_md5 == prev_valid_md5)
        bridged = bool(last_valid_md5 is not None and core_md5 == last_valid_md5)
        row["frozen_strict"] = strict
        row["frozen_bridged"] = bridged
        row["frozen"] = bridged if bridge_png else strict

        prev_was_valid = True
        prev_valid_md5 = core_md5
        last_valid_md5 = core_md5

    return out


def describe_image(path: Path) -> dict:
    """Quality metrics for one image; `readable` is False if it cannot be decoded."""
    if cv2 is None or np is None:
        raise ModuleNotFoundError("opencv-python-headless and numpy are required for describe_image()")
    data = path.read_bytes()
    core, _, _ = strip_html_tail(data)
    row = inspect_image_bytes(data)
    row["readable"] = False
    image = cv2.imdecode(np.frombuffer(core, np.uint8), cv2.IMREAD_GRAYSCALE) if core else None
    if image is None:
        return row
    row.update(
        readable=True,
        height=image.shape[0],
        width=image.shape[1],
        brightness=float(image.mean()),  # 0-255; low at night
        contrast=float(image.std()),  # near 0 for blank / "no signal" frames
        sharpness=float(cv2.Laplacian(image, cv2.CV_64F).var()),  # low when blurred
    )
    return row


def build_inventory(raw: Path, *, bridge_png_frozen: bool = True) -> pd.DataFrame:
    if pd is None or timestamps is None:
        raise ModuleNotFoundError("pandas and Pillow (for cctv.timestamps) are required for build_inventory()")
    rows = []
    paths = sorted(p for p in raw.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
    for path in paths:
        stamp, source = timestamps.resolve(path)
        rows.append(
            {
                "camera_id": path.parent.name,
                "path": str(path.relative_to(raw)),
                "timestamp": stamp,
                "ts_source": source,
                **describe_image(path),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame = frame.sort_values(["camera_id", "timestamp", "path"], ignore_index=True)

    # Compute frozen flags per camera on stripped non-placeholder `core_md5`.
    strict_col = np.zeros(len(frame), dtype=bool)
    bridged_col = np.zeros(len(frame), dtype=bool)
    frozen_col = np.zeros(len(frame), dtype=bool)
    for _, idx in frame.groupby("camera_id", sort=False).groups.items():
        subset = frame.loc[idx, ["core_md5", "white_png", "truncated_jpeg", "gst_bars", "placeholder"]].to_dict("records")
        flagged = compute_frozen_flags(subset, bridge_png=bridge_png_frozen)
        pos = list(idx)
        strict_col[pos] = [r["frozen_strict"] for r in flagged]
        bridged_col[pos] = [r["frozen_bridged"] for r in flagged]
        frozen_col[pos] = [r["frozen"] for r in flagged]

    frame["frozen_strict"] = strict_col
    frame["frozen_bridged"] = bridged_col
    frame["frozen"] = frozen_col
    frame["usable"] = frame["readable"] & (~frame["placeholder"]) & (~frame["frozen"])
    return frame


def summarise(frame: pd.DataFrame) -> pd.DataFrame:
    """Per-camera coverage: how many images, over what period, how far apart."""
    if pd is None:
        raise ModuleNotFoundError("pandas is required for summarise()")
    frame = frame.assign(gap_min=frame.groupby("camera_id")["timestamp"].diff().dt.total_seconds() / 60)
    agg_spec: dict[str, tuple[str, Any]] = {
        "images": ("path", "size"),
        "with_timestamp": ("timestamp", "count"),
        "unreadable": ("readable", lambda s: int((~s).sum())),
        "frozen": ("frozen", "sum"),
        "first": ("timestamp", "min"),
        "last": ("timestamp", "max"),
        "median_gap_min": ("gap_min", "median"),
        "max_gap_min": ("gap_min", "max"),
    }
    for col, out_name in [("white_png", "white_pngs"), ("truncated_jpeg", "truncated_jpegs"), ("gst_bars", "gst_bars")]:
        if col in frame.columns:
            agg_spec[out_name] = (col, "sum")
    return frame.groupby("camera_id").agg(**agg_spec)


def _default_raw_dir() -> Path:
    preferred = Path("data/100_cameras/cctv_images")
    return preferred if preferred.exists() else Path("data/raw")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, default=_default_raw_dir())
    parser.add_argument("--out", type=Path, default=Path("data/interim"))
    parser.add_argument("--no-bridge-png", action="store_true", help="do not bridge frozen streaks across white PNGs")
    args = parser.parse_args()

    frame = build_inventory(args.raw, bridge_png_frozen=not args.no_bridge_png)
    if frame.empty:
        raise SystemExit(f"No images found under {args.raw}")
    args.out.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.out / "images.parquet", index=False)
    summary = summarise(frame)
    summary.to_csv(args.out / "camera_summary.csv")

    total, stamped = len(frame), int(frame["timestamp"].notna().sum())
    print(f"{total} images from {frame['camera_id'].nunique()} cameras -> {args.out / 'images.parquet'}")
    print(f"timestamps: {stamped}/{total} resolved ({frame['ts_source'].value_counts().to_dict()})")
    print(
        f"unreadable: {int((~frame['readable']).sum())}, "
        f"white_png: {int(frame['white_png'].sum())}, "
        f"truncated_jpeg: {int(frame['truncated_jpeg'].sum())}, "
        f"gst_bars: {int(frame['gst_bars'].sum())}, "
        f"frozen: {int(frame['frozen'].sum())}"
    )
    if stamped:
        print(f"period: {frame['timestamp'].min()} to {frame['timestamp'].max()}")
        print(f"median gap between frames: {summary['median_gap_min'].median():.1f} min")
    missing = summary[summary["with_timestamp"] < summary["images"]]
    if len(missing):
        print(f"{len(missing)} cameras have images without a timestamp (see camera_summary.csv)")


if __name__ == "__main__":
    main()

