"""False-positive screening: eclipsing-binary signatures must be flagged."""
import pytest

from app.analysis.transit.pipeline import run_transit_pipeline
from app.synthetic import make_lightcurve, solar_a_rs

pytestmark = pytest.mark.slow


def _check(c, id_):
    return next((x for x in c["vetting"]["checks"] if x["id"] == id_), None)


def test_odd_even_depth_mismatch_flagged():
    P = 3.0
    a = solar_a_rs(P)
    lc, _ = make_lightcurve(period=2 * P, t0=1.1, rp=0.10, a_rs=a, noise_ppm=500, seed=11, baseline=27, cadence_min=10,
                            gaps=(), extra_planets=[dict(period=2 * P, t0=1.1 + P, rp=0.062, a_rs=a)])
    res = run_transit_pipeline(lc, {"max_candidates": 1, "fit": False})
    c = res["candidates"][0]
    assert abs(c["period"] - P) < 0.02 or abs(c["period"] - 2 * P) < 0.04
    oe = _check(c, "odd_even")
    if abs(c["period"] - P) < 0.02:           # folded at half the true period: depths alternate
        assert oe["status"] in ("warn", "fail"), oe


def test_secondary_eclipse_flagged():
    """Primary + secondary of similar depth: BLS may lock on P or P/2. Either way an EB signature must be flagged:
    the secondary check at P, or the odd/even depth mismatch at P/2."""
    P = 3.5
    a = solar_a_rs(P)
    lc, _ = make_lightcurve(period=P, t0=1.0, rp=0.08, a_rs=a, noise_ppm=500, seed=12, baseline=27, cadence_min=10,
                            gaps=(), extra_planets=[dict(period=P, t0=1.0 + P / 2, rp=0.07, a_rs=a)])
    res = run_transit_pipeline(lc, {"max_candidates": 1, "fit": False})
    c = res["candidates"][0]
    if abs(c["period"] - P) < 0.02:
        assert _check(c, "secondary_eclipse")["status"] in ("warn", "fail")
    else:
        assert abs(c["period"] - P / 2) < 0.02, c["period"]
        assert _check(c, "odd_even")["status"] in ("warn", "fail")


def test_clean_planet_passes_odd_even_and_secondary():
    lc, _ = make_lightcurve(period=3.0, rp=0.05, noise_ppm=500, seed=13, baseline=27, cadence_min=10, gaps=())
    res = run_transit_pipeline(lc, {"max_candidates": 1, "fit": False})
    c = res["candidates"][0]
    assert _check(c, "odd_even")["status"] in ("pass", "na")
    assert _check(c, "secondary_eclipse")["status"] == "pass"
    assert c["vetting"]["n_fail"] == 0
