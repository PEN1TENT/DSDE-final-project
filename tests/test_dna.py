import numpy as np
import pandas as pd

from cctv.dna import (
    adjusted_rand_index,
    assign_archetype_names,
    benjamini_hochberg,
    build_dna_features,
    kmeans_pp,
    kruskal_wallis_perm,
    pairwise_diff_perm,
    silhouette_samples,
)


def test_dna_features_are_zoom_invariant():
    rows = []
    for cam, mult in [(1, 1.0), (2, 3.5)]:
        for dt in ("weekday", "weekend"):
            for h in range(6, 21):
                val = (10.0 + h) * (0.8 if dt == "weekend" else 1.0) * mult
                rows.append({"camera_id": cam, "daytype": dt, "hour": h, "n_calibrated": val})
    dna, hourly = build_dna_features(pd.DataFrame(rows))
    assert np.allclose(dna.loc[1].to_numpy(), dna.loc[2].to_numpy())
    assert np.allclose(hourly.loc[1].to_numpy(), hourly.loc[2].to_numpy())


def test_kmeans_pp_and_silhouette_recover_clusters():
    rng = np.random.default_rng(7)
    c0 = rng.normal(loc=[0.0, 0.0, 0.0], scale=0.15, size=(15, 3))
    c1 = rng.normal(loc=[4.0, 0.0, 0.0], scale=0.15, size=(15, 3))
    c2 = rng.normal(loc=[0.0, 4.0, 0.0], scale=0.15, size=(15, 3))
    X = np.vstack([c0, c1, c2])
    truth = np.repeat([0, 1, 2], 15)
    labels, _, _ = kmeans_pp(X, k=3, n_init=20, seed=403)
    assert adjusted_rand_index(truth, labels) == 1.0
    assert silhouette_samples(X, labels).mean() > 0.7


def test_archetype_naming_is_deterministic():
    dna = pd.DataFrame(
        {
            "am_ratio": [0.9, 0.9, 0.8, 0.8, 1.2, 1.2],
            "midday_ratio": [1.0, 1.0, 0.8, 0.8, 0.9, 0.9],
            "pm_ratio": [1.1, 1.1, 1.5, 1.5, 1.0, 1.0],
            "night_ratio": [0.8, 0.8, 1.1, 1.1, 0.5, 0.5],
            "weekend_keep": [0.88, 0.88, 0.60, 0.60, 0.70, 0.70],
            "we_am_keep": [0.75, 0.75, 0.55, 0.55, 0.50, 0.50],
        },
        index=[10, 11, 20, 21, 30, 31],
    )
    lbl_a = np.array([0, 0, 1, 1, 2, 2])
    lbl_b = np.array([2, 2, 0, 0, 1, 1])
    new_a, names_a = assign_archetype_names(dna, lbl_a)
    new_b, names_b = assign_archetype_names(dna, lbl_b)
    assert np.array_equal(new_a, new_b)
    assert names_a.equals(names_b)
    assert set(names_a) == {
        "All-day urban & retail",
        "Evening-peak office / outbound",
        "Morning-commute arterial",
    }


def test_permutation_tests_and_fdr():
    rng = np.random.default_rng(403)
    groups = np.repeat([0, 1, 2], 20)
    shifted = np.concatenate([rng.normal(0, 1, 20), rng.normal(3, 1, 20), rng.normal(6, 1, 20)])
    identical = rng.normal(0, 1, 60)

    _, p_kw_sig = kruskal_wallis_perm(shifted, groups, n_perm=500, seed=1)
    _, p_kw_null = kruskal_wallis_perm(identical, groups, n_perm=500, seed=1)
    assert p_kw_sig < 0.01
    assert p_kw_null > 0.10

    _, p_pw_sig = pairwise_diff_perm(shifted[:20], shifted[40:], n_perm=500, seed=1)
    _, p_pw_null = pairwise_diff_perm(identical[:20], identical[40:], n_perm=500, seed=1)
    assert p_pw_sig < 0.01
    assert p_pw_null > 0.10

    raw_p = np.array([0.001, 0.02, 0.50, 0.01])
    q = benjamini_hochberg(raw_p)
    assert np.all(q >= raw_p) and np.all(q <= 1.0)
    assert q[0] <= q[3] <= q[1] <= q[2]
