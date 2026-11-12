"""Recover a capture time for an image from its filename or EXIF data.

All returned datetimes are naive and meant to be read as Bangkok local time.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

BANGKOK = timezone(timedelta(hours=7))

# Plausible range for this dataset; anything outside is treated as a non-match
# so that camera ids or counters are not mistaken for dates.
MIN_YEAR, MAX_YEAR = 2020, 2030

_SEP = r"[-_./]?"
_GAP = r"[-_ T.]?"
_TIME = rf"(?P<H>[01]\d|2[0-3]){r'[-_:.h]?'}(?P<M>[0-5]\d)(?:{r'[-_:.m]?'}(?P<S>[0-5]\d))?"

# Tried in order. Year-first comes first because it is the least ambiguous.
_PATTERNS = [
    # 2026-05-25_14-30-00, 20260525T143000, 2026.05.25 14:30
    re.compile(rf"(?<!\d)(?P<y>\d{{4}}){_SEP}(?P<m>0[1-9]|1[0-2]){_SEP}(?P<d>0[1-9]|[12]\d|3[01]){_GAP}{_TIME}(?!\d)"),
    # 25-05-2026_14-30-00 (day first, as on the camera overlays)
    re.compile(rf"(?<!\d)(?P<d>0[1-9]|[12]\d|3[01]){_SEP}(?P<m>0[1-9]|1[0-2]){_SEP}(?P<y>\d{{4}}){_GAP}{_TIME}(?!\d)"),
]
_EPOCH = re.compile(r"(?<!\d)(1[6-9]\d{8})(\d{3})?(?!\d)")


def _normalise_year(year: int) -> int:
    """Convert a Buddhist-era year (e.g. 2569) to the Gregorian one."""
    return year - 543 if year >= 2400 else year


def from_filename(name: str) -> datetime | None:
    """Parse a timestamp out of a filename, or return None."""
    for pattern in _PATTERNS:
        for match in pattern.finditer(name):
            g = match.groupdict()
            year = _normalise_year(int(g["y"]))
            if not MIN_YEAR <= year <= MAX_YEAR:
                continue
            try:
                return datetime(year, int(g["m"]), int(g["d"]), int(g["H"]), int(g["M"]), int(g["S"] or 0))
            except ValueError:
                continue
    for match in _EPOCH.finditer(name):
        moment = datetime.fromtimestamp(int(match.group(1)), tz=BANGKOK).replace(tzinfo=None)
        if MIN_YEAR <= moment.year <= MAX_YEAR:
            return moment
    return None


def from_exif(path: Path) -> datetime | None:
    """Read DateTimeOriginal / DateTime from EXIF, or return None."""
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            # 0x8769 is the Exif sub-directory, 0x9003 DateTimeOriginal, 0x0132 DateTime.
            raw = exif.get_ifd(0x8769).get(0x9003) or exif.get(0x0132)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def resolve(path: Path) -> tuple[datetime | None, str]:
    """Return (timestamp, source), source being 'filename', 'exif' or 'none'.

    File modification time is deliberately not used: it reflects when the file
    was downloaded or copied, not when the frame was captured.
    """
    stamp = from_filename(path.name)
    if stamp is not None:
        return stamp, "filename"
    stamp = from_exif(path)
    if stamp is not None:
        return stamp, "exif"
    return None, "none"
