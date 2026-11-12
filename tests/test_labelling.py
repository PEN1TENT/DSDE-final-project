import csv

import pandas as pd

from cctv.assign import make_assignments
from cctv.evaluate import agreement
from cctv.label_server import Store


def test_assignments_split_evenly_and_overlap_with_another_person():
    sample = pd.DataFrame({"path": [f"c/{i}.jpg" for i in range(100)]})
    a = make_assignments(sample, ["ann", "ben", "cat", "dan", "eve"], overlap=4, seed=0)

    assert a[a.role == "own"].path.is_unique  # every frame has exactly one main labeller
    assert set(a[a.role == "own"].path) == set(sample.path)
    assert a.groupby("who").size().eq(24).all()  # 20 own + 4 overlap each
    pairs = a[a.role == "overlap"].merge(a[a.role == "own"], on="path")
    assert len(pairs) == 20 and (pairs.who_x != pairs.who_y).all()


def test_agreement_compares_the_two_people_on_shared_frames():
    zero = dict(motorcycle=0, bus=0, truck=0, bicycle=0, unusable=0)
    labels = pd.DataFrame([
        {"path": "a", "role": "own", "car": 3, **zero},
        {"path": "a", "role": "overlap", "car": 5, **zero},
        {"path": "b", "role": "own", "car": 2, **zero},
        {"path": "b", "role": "overlap", "car": 2, **zero},
        {"path": "c", "role": "own", "car": 9, **zero},  # only one person: not a pair
    ])
    total = agreement(labels).set_index("class").loc["total"]
    assert total.pairs == 2
    assert total.mae == 1.0  # |3-5| and |2-2|
    assert total.exact_match == 0.5


def test_store_checks_keys_and_saves_per_person(tmp_path):
    with (tmp_path / "tokens.csv").open("w", newline="") as f:
        csv.writer(f).writerows([["who", "key"], ["ann", "k1"], ["admin", "k0"]])
    with (tmp_path / "assignments.csv").open("w", newline="") as f:
        csv.writer(f).writerows([["who", "path", "role", "order"], ["ann", "c/1.jpg", "own", 0]])
    store = Store(tmp_path)

    assert store.check("ann", "k1")
    assert not store.check("ann", "k0") and not store.check("ann", None) and not store.check("bob", "k1")
    store.save("ann", {"path": "c/1.jpg", "car": "2", "note": "ok"})
    saved = Store(tmp_path).labels["ann"]["c/1.jpg"]  # reload from disk
    assert saved["car"] == "2" and saved["note"] == "ok"
