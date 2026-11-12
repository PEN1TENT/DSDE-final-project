from datetime import datetime

import numpy as np
import pytest

from cctv import timestamps
from cctv.detect import covered_fraction


@pytest.mark.parametrize(
    "name, expected",
    [
        ("20260525_143000.jpg", datetime(2026, 5, 25, 14, 30, 0)),
        ("cam137_2026-05-25_14-30-05.jpg", datetime(2026, 5, 25, 14, 30, 5)),
        ("2026-05-25T14:30.png", datetime(2026, 5, 25, 14, 30, 0)),
        ("137_20260525143000.jpg", datetime(2026, 5, 25, 14, 30, 0)),
        ("25-05-2026_14-30-00.jpg", datetime(2026, 5, 25, 14, 30, 0)),
        ("25-05-2569 14.30.00.jpg", datetime(2026, 5, 25, 14, 30, 0)),  # Buddhist era
        ("1779694200.jpg", datetime(2026, 5, 25, 14, 30, 0)),  # epoch seconds, Bangkok time
        ("1779694200123.jpg", datetime(2026, 5, 25, 14, 30, 0)),  # epoch milliseconds
    ],
)
def test_from_filename(name, expected):
    assert timestamps.from_filename(name) == expected


@pytest.mark.parametrize("name", ["137.jpg", "frame_000123.jpg", "cam_1071_0005.jpg", "20261345_990000.jpg"])
def test_from_filename_rejects_non_dates(name):
    assert timestamps.from_filename(name) is None


def test_covered_fraction_counts_overlap_once():
    boxes = np.array([[0, 0, 50, 100], [25, 0, 50, 100]])
    assert covered_fraction(boxes, width=100, height=100) == pytest.approx(0.5)
    assert covered_fraction(np.empty((0, 4)), width=100, height=100) == 0.0
