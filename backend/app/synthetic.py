"""Synthetic light curves with known injected transits, for tests and offline demos.

These are clearly labelled synthetic data and are never presented as astronomical observations.
"""
from __future__ import annotations

import numpy as np

from .core.lightcurve import LightCurve


def transit_model(t, period, t0, rp, a_rs, inc_deg=89.0, u=(0.4, 0.25), ecc=0.0, w=90.0):
    import batman
    p = batman.TransitParams()
    p.t0, p.per, p.rp, p.a, p.inc = t0, period, rp, a_rs, inc_deg
    p.ecc, p.w, p.u, p.limb_dark = ecc, w, list(u), "quadratic"
    m = batman.TransitModel(p, np.asarray(t, dtype=float))
    return m.light_curve(p)


def solar_a_rs(period: float) -> float:
    """a/Rs for a circular orbit around a star of solar mean density (rho = 1.41 g/cc)."""
    return 4.21 * period ** (2.0 / 3.0)


def make_lightcurve(
    period=3.2, t0=1.1, rp=0.05, a_rs=None, inc_deg=89.0, baseline=27.0, cadence_min=2.0,
    noise_ppm=500.0, gaps=((13.0, 14.2),), variability_amp=0.0, variability_period=5.0,
    seed=0, extra_planets=(), mission="tess",
) -> tuple[LightCurve, dict]:
    rng = np.random.default_rng(seed)
    a_rs = solar_a_rs(period) if a_rs is None else a_rs
    t = np.arange(0.0, baseline, cadence_min / 1440.0)
    for g0, g1 in gaps:
        t = t[(t < g0) | (t > g1)]
    flux = transit_model(t, period, t0, rp, a_rs, inc_deg)
    truth = {"planets": [dict(period=period, t0=t0, rp=rp, a_rs=a_rs, inc_deg=inc_deg)]}
    for ep in extra_planets:
        flux = flux * transit_model(t, ep["period"], ep["t0"], ep["rp"], ep.get("a_rs", solar_a_rs(ep["period"])), ep.get("inc_deg", 89.0))
        truth["planets"].append(ep)
    if variability_amp:
        flux = flux * (1 + variability_amp * np.sin(2 * np.pi * t / variability_period + 0.7))
    sigma = noise_ppm * 1e-6
    flux = flux + rng.normal(0, sigma, len(t))
    # depth of the primary signal for convenience
    truth["depth_ppm"] = float(rp ** 2 * 1e6)
    truth["noise_ppm"] = noise_ppm
    q = np.zeros(len(t), dtype=np.int64)
    lc = LightCurve(time=t, flux=flux, flux_err=np.full(len(t), sigma), quality=q,
                    time_format="btjd" if mission == "tess" else "relative",
                    time_offset_jd=2457000.0 if mission == "tess" else None,
                    mission=mission, meta={"synthetic": True})
    return lc, truth
