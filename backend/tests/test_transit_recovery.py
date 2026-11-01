"""Scientific validation of the transit workflow using synthetic data with known injected signals.

Synthetic light curves are the only ground truth available offline. They validate the algorithms
(recovery of period, depth, radius ratio; behaviour on noise and variability) but not performance
on real, correlated-noise photometry, which must be assessed on archive data (see docs/DEMO.md).
"""
import json

import numpy as np
import pytest

from app.analysis.transit.pipeline import run_transit_pipeline
from app.synthetic import make_lightcurve, solar_a_rs

pytestmark = pytest.mark.slow
SIGNAL_KINDS = {"new_unvalidated_signal", "matches_published_planet", "matches_known_candidate"}


def signals(res):
    return [c for c in res["candidates"] if c["kind"] in SIGNAL_KINDS]


def nearest(res, period, tol=0.01):
    cs = [c for c in signals(res) if abs(c["period"] - period) / period < tol]
    return min(cs, key=lambda c: abs(c["period"] - period)) if cs else None


@pytest.fixture(scope="module")
def clean_result():
    lc, truth = make_lightcurve(period=3.2, rp=0.05, noise_ppm=500, seed=1, baseline=20, cadence_min=10)
    return run_transit_pipeline(lc, {"max_candidates": 2}), truth


def test_recovers_period_depth_and_radius_ratio(clean_result):
    res, truth = clean_result
    c = nearest(res, 3.2, 0.002)
    assert c is not None, res["summary"]
    fit = c["fit"]["params"]
    assert abs(fit["period"]["value"] - 3.2) < 5 * fit["period"]["err"] + 1e-3
    assert abs(fit["rp_rs"]["value"] - 0.05) < max(3 * fit["rp_rs"]["err"], 0.003)
    assert 0.8 < c["depth"] * 1e6 / truth["depth_ppm"] < 1.3   # box depth ≈ rp² (limb darkening/ingress)
    assert c["sde"] > 12 and c["vetting"]["n_fail"] == 0


def test_epoch_recovered(clean_result):
    res, _ = clean_result
    c = nearest(res, 3.2, 0.002)
    ph = ((c["t0"] - 1.1 + 1.6) % 3.2) - 1.6
    assert abs(ph) < 0.02


def test_never_claims_confirmation(clean_result):
    res, _ = clean_result
    text = json.dumps(res).lower()
    assert "confirmed planet" not in text.replace("not confirmed planets", "").replace("not a confirmed", "")
    for c in res["candidates"]:
        assert c["kind"] != "confirmed"
    assert "candidate" in res["summary"].lower()


def test_no_radius_without_stellar_radius(clean_result):
    res, _ = clean_result
    c = nearest(res, 3.2, 0.002)
    d = c["fit"]["derived"]
    assert d["planet_radius_earth"] is None and "stellar radius" in d["radius_note"]


def test_radius_reported_when_stellar_radius_given():
    lc, _ = make_lightcurve(period=3.2, rp=0.05, noise_ppm=500, seed=1, baseline=20, cadence_min=10)
    res = run_transit_pipeline(lc, {"max_candidates": 1, "star": {"radius_rsun": 1.0, "radius_err_rsun": 0.05}})
    rad = nearest(res, 3.2, 0.002)["fit"]["derived"]["planet_radius_earth"]
    assert rad and abs(rad["value"] - 0.05 * 109.076) < 3 * rad["err"] + 0.5
    assert rad["err"] > 0


def test_two_planets_both_preserved():
    lc, _ = make_lightcurve(period=2.1, rp=0.04, noise_ppm=600, seed=3, baseline=27, cadence_min=10,
                            extra_planets=[dict(period=5.7, t0=0.9, rp=0.035)])
    res = run_transit_pipeline(lc, {"max_candidates": 3})
    assert nearest(res, 2.1, 0.005) is not None and nearest(res, 5.7, 0.005) is not None
    # calibration check: the truth must lie within 2 sigma of the *reported* uncertainty
    rp = nearest(res, 5.7, 0.005)["fit"]["params"]["rp_rs"]
    assert abs(rp["value"] - 0.035) < 2 * rp["err"]
    rp1 = nearest(res, 2.1, 0.005)["fit"]["params"]["rp_rs"]
    assert abs(rp1["value"] - 0.04) < 2 * rp1["err"]


def test_observation_gap_does_not_break_recovery():
    lc, _ = make_lightcurve(period=4.0, rp=0.05, noise_ppm=500, seed=5, baseline=27, cadence_min=10,
                            gaps=((8.0, 12.0), (19.0, 21.0)))
    res = run_transit_pipeline(lc, {"max_candidates": 1})
    assert nearest(res, 4.0, 0.005) is not None


def test_stellar_variability_not_reported_as_planet():
    lc, _ = make_lightcurve(period=7.4, rp=0.035, noise_ppm=600, seed=2, baseline=27, cadence_min=10,
                            variability_amp=0.004, variability_period=5.0)
    res = run_transit_pipeline(lc, {"max_candidates": 3})
    assert nearest(res, 7.4, 0.01) is not None, [(c["period"], c["kind"]) for c in res["candidates"]]
    # whatever else was found near the variability period must not be presented as a transit signal
    for c in res["candidates"]:
        if abs(c["period"] - 5.0) < 0.6 or abs(c["period"] - 10.0) < 1.0:
            assert c["kind"] in ("likely_variability", "weak_signal"), (c["period"], c["kind"])


@pytest.mark.parametrize("seed", [100, 117, 230])  # 100 and 230 were false alarms under SDE-only criteria
def test_pure_noise_gives_no_detection(seed):
    lc, _ = make_lightcurve(rp=0.0, noise_ppm=500, seed=seed, baseline=27, cadence_min=10)
    res = run_transit_pipeline(lc, {"max_candidates": 1})
    assert signals(res) == []
    assert any("No signal reached" in w for w in res["warnings"])


def test_shallow_planet_below_noise_is_not_claimed():
    lc, _ = make_lightcurve(period=6.0, rp=0.005, noise_ppm=1500, seed=9, baseline=27, cadence_min=10)
    res = run_transit_pipeline(lc, {"max_candidates": 1})
    assert signals(res) == []


def test_known_planet_and_candidate_labels_are_distinct():
    lc, _ = make_lightcurve(period=3.2, rp=0.05, noise_ppm=500, seed=1, baseline=20, cadence_min=10)
    pub = run_transit_pipeline(lc, {"max_candidates": 1, "known_planets": [{"name": "Test b", "period": 3.2005, "status": "published"}]})
    assert pub["candidates"][0]["kind"] == "matches_published_planet"
    assert "not an independent confirmation" in pub["candidates"][0]["status_text"]
    toi = run_transit_pipeline(lc, {"max_candidates": 1, "known_planets": [{"name": "TOI-1.01", "period": 3.2, "status": "candidate"}]})
    assert toi["candidates"][0]["kind"] == "matches_known_candidate"
    new = run_transit_pipeline(lc, {"max_candidates": 1, "known_planets": [{"name": "Other", "period": 11.0, "status": "published"}]})
    assert new["candidates"][0]["kind"] == "new_unvalidated_signal"


def test_quality_flags_remove_cadences_and_are_recorded():
    lc, _ = make_lightcurve(period=3.2, rp=0.05, noise_ppm=500, seed=1, baseline=20, cadence_min=10)
    q = np.zeros(len(lc), dtype=np.int64)
    q[::10] = 1    # AttitudeTweak: in the default mask
    q[5::10] = 1024  # CollateralCosmic: only in the 'hard' mask
    lc.quality = q
    res = run_transit_pipeline(lc, {"max_candidates": 1, "search_bin_minutes": None})
    rec = res["provenance"]["preprocessing_pass1"]
    assert rec["removed_quality_flag"] == int(np.sum(q == 1))
    hard = run_transit_pipeline(lc, {"max_candidates": 1, "quality_mask": "hard", "search_bin_minutes": None})
    assert hard["provenance"]["preprocessing_pass1"]["removed_quality_flag"] == int(np.sum(q > 0))


def test_provenance_records_parameters_and_versions():
    lc, _ = make_lightcurve(period=3.2, rp=0.05, noise_ppm=500, seed=1, baseline=20, cadence_min=10)
    res = run_transit_pipeline(lc, {"max_candidates": 1, "sde_threshold": 9.0})
    p = res["provenance"]
    assert p["parameters"]["sde_threshold"] == 9.0
    assert "preprocessing_pass1" in p and "library_note" in p
    assert p["parameters"]["effective_max_duration_days"] <= 0.25 + 1e-9


def test_original_lightcurve_is_not_modified():
    lc, _ = make_lightcurve(period=3.2, rp=0.05, noise_ppm=500, seed=1, baseline=20, cadence_min=10)
    t0, f0 = lc.time.copy(), lc.flux.copy()
    run_transit_pipeline(lc, {"max_candidates": 1})
    assert np.array_equal(lc.time, t0) and np.array_equal(lc.flux, f0)


def test_short_period_duration_limited_physically():
    from app.analysis.transit.search import max_duration_for_period
    assert max_duration_for_period(0.5) <= 0.5 / 3 + 1e-12
    assert max_duration_for_period(10) < 0.5
