"""End-to-end transit workflow: preprocess → BLS → mask-and-redetrend → vet → fit → package."""
from __future__ import annotations

from typing import Any, Callable

import numpy as np

from ...core.lightcurve import LightCurve
from .fit import fit_transit, model_curve
from .preprocess import bin_lightcurve, preprocess
from .search import run_bls, transit_mask
from .vetting import vet_candidate

DEFAULT_PARAMS: dict[str, Any] = {
    "quality_mask": "default", "detrend": True, "window_days": None,
    "min_period": None, "max_period": None, "min_transits": 2, "max_duration": 0.5,
    "max_candidates": 3, "sde_threshold": 8.5, "min_depth_snr": 7.1, "oversample": 3.0,
    "search_bin_minutes": 10.0, "fit": True, "mcmc": False, "mcmc_steps": 1500,
    "star": {"teff": None, "radius_rsun": None, "radius_err_rsun": None, "mass_msun": None},
    "known_planets": [],
}

Progress = Callable[[float, str], None]


def _noop(p: float, msg: str) -> None:
    pass


def _for_search(flat: LightCurve, bin_minutes: float | None) -> LightCurve:
    """Bin fine-cadence data for the (expensive) BLS search only; fitting and folding use the full data."""
    if bin_minutes and flat.median_cadence_days() * 1440 < 0.7 * bin_minutes:
        return bin_lightcurve(flat, bin_minutes / 1440.0)
    return flat


def _thin_xy(x, y, n=6000):
    x, y = np.asarray(x), np.asarray(y)
    if len(x) <= n:
        return x.tolist(), y.tolist()
    idx = np.linspace(0, len(x) - 1, n).astype(int)
    return x[idx].tolist(), y[idx].tolist()


def fold_binned(time, flux, period, t0, nbins=100, half_window=None):
    ph = ((time - t0 + 0.5 * period) % period) - 0.5 * period
    if half_window is None:
        half_window = 0.5 * period
    m = np.abs(ph) <= half_window
    ph, f = ph[m], flux[m]
    edges = np.linspace(-half_window, half_window, nbins + 1)
    idx = np.digitize(ph, edges) - 1
    xs, ys, es = [], [], []
    for k in range(nbins):
        s = idx == k
        if s.sum() >= 3:
            xs.append(float(ph[s].mean()))
            ys.append(float(f[s].mean()))
            es.append(float(f[s].std(ddof=1) / np.sqrt(s.sum())))
    return xs, ys, es


def run_transit_pipeline(lc: LightCurve, params: dict[str, Any] | None = None,
                         progress: Progress = _noop) -> dict[str, Any]:
    p = {**DEFAULT_PARAMS, **(params or {})}
    p["star"] = {**DEFAULT_PARAMS["star"], **(p.get("star") or {})}
    warnings: list[str] = []
    prov: dict[str, Any] = {"parameters": {k: v for k, v in p.items() if k != "known_planets"}}

    # A running-median filter of window W cannot preserve features longer than ~W/3, so any dip
    # longer than that is filter residue by construction. Cap the searched duration accordingly.
    window = p["window_days"] or 0.75
    max_dur = p["max_duration"]
    if p["detrend"] and max_dur > window / 3.0:
        max_dur = window / 3.0
        warnings.append(f"Maximum searched transit duration limited to {max_dur * 24:.1f} h (detrending window {window:g} d ÷ 3). "
                        "Increase the detrending window (and max duration) to search for longer transits, "
                        "e.g. around evolved stars.")
    p["max_duration"] = max_dur
    p["window_days"] = window
    prov["parameters"]["effective_max_duration_days"] = max_dur

    progress(0.02, "Cleaning and detrending")
    flat1, rec1 = preprocess(lc, quality_mask=p["quality_mask"], detrend=p["detrend"],
                             window_days=p["window_days"], max_duration_days=p["max_duration"])
    if len(flat1) < 100:
        raise ValueError(f"Only {len(flat1)} usable points after cleaning; a transit search needs at least 100.")
    prov["preprocessing_pass1"] = rec1

    progress(0.10, "Searching for periodic dips (BLS)")
    s1 = run_bls(_for_search(flat1, p["search_bin_minutes"]), min_period=p["min_period"], max_period=p["max_period"], min_transits=p["min_transits"],
                 max_duration=p["max_duration"], max_candidates=p["max_candidates"],
                 sde_threshold=p["sde_threshold"], min_depth_snr=p["min_depth_snr"], oversample=max(1.0, p["oversample"] / 2), progress=progress)
    search, flat = s1, flat1

    significant = [c for c in s1["candidates"] if not c["below_threshold"]]
    if p["detrend"] and significant:
        progress(0.66, "Re-detrending with detected transits masked")
        # Build a mask on the *original* (sorted, cleaned) time grid used for pass 2
        tmp = lc.sorted()
        m = np.zeros(len(tmp), bool)
        for c in significant:
            m |= transit_mask(tmp.time, c["period"], c["t0"], c["duration"], factor=2.0)
        flat2, rec2 = preprocess(lc, quality_mask=p["quality_mask"], detrend=True,
                                 window_days=p["window_days"], max_duration_days=p["max_duration"],
                                 transit_mask=m)
        prov["preprocessing_pass2"] = rec2
        s2 = run_bls(_for_search(flat2, p["search_bin_minutes"]), min_period=p["min_period"], max_period=p["max_period"], min_transits=p["min_transits"],
                     max_duration=p["max_duration"], max_candidates=p["max_candidates"],
                     sde_threshold=p["sde_threshold"], min_depth_snr=p["min_depth_snr"], oversample=p["oversample"])
        # Keep the pass-2 result unless it lost the signal entirely
        if any(not c["below_threshold"] for c in s2["candidates"]):
            search, flat = s2, flat2
        else:
            warnings.append("Re-detrending with the transits masked removed the signal; keeping the first-pass result. "
                            "The signal may be sensitive to detrending.")
    cands = search["candidates"]
    if not cands:
        raise ValueError("The search returned no candidates.")
    if all(c["below_threshold"] for c in cands):
        warnings.append(f"No signal reached both SDE ≥ {p['sde_threshold']:g} and depth S/N ≥ {p['min_depth_snr']:g}. The strongest peak is shown for inspection only "
                        "and should not be interpreted as a detection.")

    out_cands: list[dict[str, Any]] = []
    for i, c in enumerate(cands):
        progress(0.70 + 0.25 * (i + 1) / len(cands), f"Vetting and fitting candidate {c['rank']}")
        vet = vet_candidate(c, _for_search(flat, p["search_bin_minutes"]), cands, sde_threshold=p["sde_threshold"], min_depth_snr=p["min_depth_snr"], known_planets=p["known_planets"])
        fit = None
        if p["fit"] and (not c["below_threshold"] or i == 0):
            others = np.zeros(len(flat), bool)
            for o in cands:
                if o is not c and not o["below_threshold"]:
                    others |= transit_mask(flat.time, o["period"], o["t0"], o["duration"], factor=1.5)
            fit = fit_transit(flat, c, exclude_mask=others, teff=p["star"]["teff"], star_radius_rsun=p["star"]["radius_rsun"],
                              star_radius_err=p["star"]["radius_err_rsun"], star_mass_msun=p["star"]["mass_msun"],
                              mcmc=p["mcmc"], mcmc_steps=p["mcmc_steps"])
        P, t0, dur = c["period"], c["t0"], c["duration"]
        fx, fy, fe = fold_binned(flat.time, flat.flux, P, t0, nbins=120, half_window=min(0.5 * P, max(5 * dur, 0.3)))
        model = None
        if fit and fit.get("ok"):
            th = fit["_theta"]
            ph = np.linspace(-min(0.5 * P, max(5 * dur, 0.3)), min(0.5 * P, max(5 * dur, 0.3)), 600)
            model = {"phase": ph.tolist(), "flux": model_curve([0.0, th[1], th[2], th[3], th[4]], fit["_u"], ph,
                                                                flat.median_cadence_days()).tolist()}
        # label: catalogue relationship + significance; never "confirmed"
        sinus = any(ch["id"] == "sinusoid_alternative" and ch["status"] == "warn" for ch in vet["checks"])
        if vet["catalog_match"]:
            kind = ("matches_published_planet" if vet["catalog_match"].get("status") in ("published", "confirmed")
                    else "matches_known_candidate")
        elif c["below_threshold"]:
            kind = "weak_signal"
        elif sinus:
            kind = "likely_variability"
        else:
            kind = "new_unvalidated_signal"
        clean_fit = None if fit is None else {k: v for k, v in fit.items() if not k.startswith("_")}
        out_cands.append({
            "rank": c["rank"], "kind": kind,
            "status_text": _status_text(kind, vet),
            "period": P, "t0": t0, "duration": dur, "depth": c["depth"], "depth_err": c["depth_err"],
            "depth_snr": c["depth_snr"], "sde": c["sde"], "below_threshold": c["below_threshold"],
            "n_transits_observed": c["n_transits_observed"],
            "t0_absolute_jd": (None if flat.time_offset_jd is None else flat.time_offset_jd + t0),
            "vetting": vet, "fit": clean_fit,
            "folded": {"phase": fx, "flux": fy, "err": fe}, "model": model,
        })

    # series for plotting
    raw_t, raw_f = _thin_xy(lc.time, lc.flux / np.nanmedian(lc.flux))
    fl_t, fl_f = _thin_xy(flat.time, flat.flux)
    trend = flat.meta.get("trend")
    tr_t, tr_f = _thin_xy(flat.time, trend) if trend is not None else ([], [])
    prov["library_note"] = "BLS: astropy.timeseries.BoxLeastSquares; model: batman; fit: scipy.optimize.least_squares"
    progress(0.98, "Packaging results")
    return {
        "module": "transit_bls", "candidates": out_cands, "warnings": warnings,
        "series": {"raw": {"time": raw_t, "flux": raw_f}, "flattened": {"time": fl_t, "flux": fl_f},
                   "trend": {"time": tr_t, "flux": tr_f}, "time_format": lc.time_format,
                   "time_offset_jd": lc.time_offset_jd},
        "periodograms": search["spectra"], "search": {k: v for k, v in search.items() if k != "spectra" and k != "candidates"},
        "provenance": prov,
        "summary": _summary(out_cands),
    }


def _status_text(kind: str, vet: dict) -> str:
    base = {
        "matches_published_planet": "Consistent with a published planet in the catalogue (not an independent confirmation)",
        "new_unvalidated_signal": "New unvalidated transit-like signal (candidate only)",
        "matches_known_candidate": "Consistent with a previously catalogued candidate (e.g. TOI/KOI), not a confirmed planet",
        "weak_signal": "Weak peak below the detection threshold (not a detection)",
        "likely_variability": "Periodic dip better described by a sinusoid: probable stellar variability or systematic, not a transit",
    }[kind]
    if vet["n_fail"]:
        base += f"; {vet['n_fail']} vetting check(s) failed"
    return base


def _summary(cands: list[dict]) -> str:
    sig = [c for c in cands if c["kind"] in ("new_unvalidated_signal", "matches_published_planet", "matches_known_candidate")]
    if not sig:
        return "No significant periodic transit-like signal was found."
    parts = [f"P={c['period']:.4f} d (SDE {c['sde']:.1f}, depth {c['depth'] * 1e6:.0f} ppm)" for c in sig]
    return f"{len(sig)} transit-like signal(s) above threshold: " + "; ".join(parts) + ". These are candidates, not confirmed planets."
