"""Box Least Squares periodicity search with iterative candidate extraction.

Uses astropy.timeseries.BoxLeastSquares. After each detection the in-transit points are masked
and the search is repeated, so several plausible signals can be preserved rather than forcing a
single answer. A peak below the SDE threshold is still returned (flagged ``below_threshold``) when
it is the best the data offer, so users can see what the search found without it being
over-sold.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from astropy.timeseries import BoxLeastSquares

from ...core.lightcurve import LightCurve

MAX_GRID = 400_000


def max_duration_for_period(period: float, ceiling: float = 0.5) -> float:
    """Longest physically plausible transit duration at a given period.

    Central-transit duration around a Sun-like star is ≈ 0.0753·P^(1/3) days (circular orbit).
    A factor 2.5 margin admits evolved/low-density stars, and the duration is never allowed to
    exceed a third of the period. Without this limit a BLS search happily reports 'transits'
    that cover most of the orbit at short periods, which are noise or detrending residuals.
    """
    return float(min(ceiling, 2.5 * 0.0753 * period ** (1 / 3), period / 3.0))


def duration_grid(period_lo: float, period_hi: float, ceiling: float = 0.5, cadence: float = 0.0,
                  n: int = 8) -> np.ndarray:
    hi = max_duration_for_period(period_hi, ceiling)
    hi = min(hi, 0.9 * period_lo)
    lo = max(0.02, 1.5 * cadence) if cadence else 0.02
    lo = min(lo, hi / 2.5)
    return np.geomspace(lo, hi, n)


def period_segments(lo: float, hi: float, ratio: float = 2.0) -> list[tuple[float, float]]:
    edges = [lo]
    while edges[-1] * ratio < hi:
        edges.append(edges[-1] * ratio)
    edges.append(hi)
    return [(a, b) for a, b in zip(edges[:-1], edges[1:]) if b > a * 1.0001]


def period_bounds(baseline: float, min_period: float | None, max_period: float | None,
                  min_transits: int = 2) -> tuple[float, float]:
    lo = 0.5 if min_period is None else min_period
    hi_auto = baseline / min_transits
    hi = hi_auto if max_period is None else min(max_period, hi_auto)
    if hi <= lo:
        raise ValueError(f"Baseline {baseline:.2f} d is too short for periods ≥ {lo} d with {min_transits}+ transits.")
    return lo, hi


def compute_sde(power: np.ndarray) -> tuple[float, np.ndarray]:
    """SDE of the BLS spectrum after removing the slow trend of the power with period."""
    n = len(power)
    w = max(11, (n // 40) | 1)
    # running median via cumulative approach (pandas for simplicity)
    import pandas as pd
    trend = pd.Series(power).rolling(w, center=True, min_periods=3).median().to_numpy()
    flat = power - trend
    sd = np.nanstd(flat)
    sde = float((np.nanmax(flat) - np.nanmean(flat)) / sd) if sd > 0 else 0.0
    return sde, flat


def transit_mask(time: np.ndarray, period: float, t0: float, duration: float, factor: float = 1.5) -> np.ndarray:
    ph = ((time - t0 + 0.5 * period) % period) - 0.5 * period
    return np.abs(ph) < 0.5 * duration * factor


def _power_segmented(t, y, dy, lo, hi, ceiling, oversample, cadence):
    """BLS over period segments, each with its own physically-limited duration grid."""
    bls = BoxLeastSquares(t, y, dy=dy)
    P, pw, dep, dep_e, snr, dur, t0s, ll = ([] for _ in range(8))
    for a, b in period_segments(lo, hi):
        durs = duration_grid(a, b, ceiling, cadence)
        ff = max(1.0 / oversample, 1e-3)
        periods = bls.autoperiod(durs, minimum_period=a, maximum_period=b, frequency_factor=ff)
        while len(periods) > MAX_GRID:
            ff *= 1.5
            periods = bls.autoperiod(durs, minimum_period=a, maximum_period=b, frequency_factor=ff)
        r = bls.power(periods, durs, objective="likelihood")
        P.append(r.period); pw.append(r.power); dep.append(r.depth); dep_e.append(r.depth_err)
        snr.append(r.depth_snr); dur.append(r.duration); t0s.append(r.transit_time); ll.append(r.log_likelihood)
    cat = lambda x: np.concatenate(x)
    return bls, cat(P), cat(pw), cat(dep), cat(dep_e), cat(snr), cat(dur), cat(t0s), cat(ll)


def run_bls(lc: LightCurve, *, min_period=None, max_period=None, min_transits: int = 2,
            max_duration: float = 0.5, max_candidates: int = 3, sde_threshold: float = 8.5,
            oversample: float = 3.0, progress=None, min_depth_snr: float = 7.1) -> dict[str, Any]:
    t, y, dy = lc.time, lc.flux, lc.flux_err
    baseline = float(t.max() - t.min())
    lo, hi = period_bounds(baseline, min_period, max_period, min_transits)
    cadence = lc.median_cadence_days()

    candidates: list[dict[str, Any]] = []
    spectra: list[dict[str, Any]] = []
    work = np.ones(len(t), bool)
    n_periods = 0
    for k in range(max_candidates):
        if work.sum() < 100:
            break
        bls, P_, power, depth, depth_err, depth_snr, dur_, t0_, ll_ = _power_segmented(
            t[work], y[work], dy[work], lo, hi, max_duration, oversample, cadence)
        n_periods = len(P_)
        sde, flat = compute_sde(power)
        i = int(np.nanargmax(power))
        P, dur, t0 = float(P_[i]), float(dur_[i]), float(t0_[i])
        stats = bls.compute_stats(P, dur, t0)
        cand = {
            "rank": k + 1, "period": P, "duration": dur, "t0": t0,
            "depth": float(depth[i]), "depth_err": float(depth_err[i]),
            "depth_snr": float(depth_snr[i]), "sde": sde,
            "bls_log_likelihood": float(ll_[i]),
            "n_transits_observed": int(np.sum(np.asarray(stats["per_transit_count"]) > 0)),
            "below_threshold": bool(sde < sde_threshold or float(depth_snr[i]) < min_depth_snr),
            "_stats": stats,
        }
        candidates.append(cand)
        spectra.append({"rank": k + 1, "period": _thin(P_), "power": _thin(power), "sde_flattened": _thin(flat)})
        if progress:
            progress(0.15 + 0.5 * (k + 1) / max_candidates, f"BLS pass {k + 1}/{max_candidates}: P={P:.4f} d, SDE={sde:.1f}")
        if cand["below_threshold"]:
            break  # nothing further worth extracting
        work &= ~transit_mask(t, P, t0, dur)
    return {"candidates": candidates, "spectra": spectra, "period_range": [lo, hi],
            "n_periods_last": int(n_periods), "sde_threshold": sde_threshold, "min_depth_snr": min_depth_snr,
            "duration_rule": "max duration = min(ceiling, 2.5·0.0753·P^(1/3) d, P/3), per period segment"}


def _thin(a: np.ndarray, n: int = 4000) -> list[float]:
    a = np.asarray(a, float)
    if len(a) <= n:
        return a.tolist()
    idx = np.linspace(0, len(a) - 1, n).astype(int)
    return a[idx].tolist()
