"""Transit model fitting with batman and parameter uncertainties.

Free parameters: mid-transit time T0 (near the data centre, to decorrelate from P), period P,
planet/star radius ratio Rp/Rs, scaled semi-major axis a/Rs and impact parameter b.
Limb darkening is *fixed* (quadratic) - a stated assumption, not a fit. Eccentricity is fixed to 0.

Uncertainties: covariance from the least-squares Jacobian (scaled by reduced χ²), and optionally
an emcee posterior. Both are conditional on the fixed assumptions above and on white noise, so
they are likely underestimates for real photometry with correlated noise.
"""
from __future__ import annotations

from typing import Any

import batman
import numpy as np
from scipy.optimize import least_squares

from ...core.lightcurve import LightCurve

R_SUN_IN_R_EARTH = 109.076
G_CGS = 6.6743e-8
RHO_SUN = 1.41  # g/cm^3


def default_limb_darkening(teff: float | None) -> tuple[tuple[float, float], str]:
    """Very coarse quadratic LD for optical bandpasses; replaced by user input when available."""
    if teff is None:
        return (0.40, 0.25), "generic (u1=0.40, u2=0.25); no stellar Teff supplied"
    table = [(3500, (0.50, 0.25)), (4500, (0.52, 0.22)), (5500, (0.44, 0.27)), (6200, (0.36, 0.29)),
             (7000, (0.30, 0.30))]
    best = min(table, key=lambda r: abs(r[0] - teff))
    return best[1], f"coarse Teff-based approximation for Teff≈{best[0]} K; replace with tabulated values for publication"


def _model(theta, t, u, supersample, exp_time):
    t0, per, rp, a, b = theta
    p = batman.TransitParams()
    p.t0, p.per, p.rp, p.a = t0, per, rp, a
    p.inc = np.degrees(np.arccos(np.clip(b / a, 0, 1)))
    p.ecc, p.w, p.u, p.limb_dark = 0.0, 90.0, list(u), "quadratic"
    m = batman.TransitModel(p, t, supersample_factor=supersample, exp_time=exp_time) if supersample > 1 \
        else batman.TransitModel(p, t)
    return m.light_curve(p)


def phase_window_mask(time, period, t0, half_width):
    ph = ((time - t0 + 0.5 * period) % period) - 0.5 * period
    return np.abs(ph) < half_width


def fit_transit(lc: LightCurve, cand: dict[str, Any], *, teff: float | None = None,
                star_radius_rsun: float | None = None, star_radius_err: float | None = None,
                star_mass_msun: float | None = None, mcmc: bool = False, mcmc_steps: int = 1500,
                seed: int = 0, exclude_mask: np.ndarray | None = None) -> dict[str, Any]:
    P0, dur0, t00, depth0 = cand["period"], cand["duration"], cand["t0"], cand["depth"]
    u, u_note = default_limb_darkening(teff)

    win = max(3.0 * dur0, 0.25)
    sel = phase_window_mask(lc.time, P0, t00, win)
    n_excluded = 0
    if exclude_mask is not None:
        n_excluded = int((sel & exclude_mask).sum())
        sel = sel & ~exclude_mask   # in-transit points of *other* signals must not bias this fit
    t, y, e = lc.time[sel], lc.flux[sel], lc.flux_err[sel]
    if len(t) < 30:
        return {"ok": False, "reason": "Too few in-window points to fit a transit model."}
    cad = lc.median_cadence_days()
    ss, exp = (7, cad) if cad > 10 / 1440 else (1, cad)

    # move T0 to the transit nearest the middle of the data to decorrelate T0 and P
    n_mid = np.round((np.median(lc.time) - t00) / P0)
    t0_ref = t00 + n_mid * P0

    rp0 = float(np.sqrt(max(depth0, 1e-6)))
    # initial a/Rs from the duration of a central transit: T ≈ P/π · 1/a
    a0 = float(np.clip(P0 / (np.pi * dur0), 2.0, 60.0))
    x0 = np.array([t0_ref, P0, rp0, a0, 0.3])
    lo = np.array([t0_ref - 0.5 * dur0 - 0.05, P0 * 0.995, 0.002, 1.5, 0.0])
    hi = np.array([t0_ref + 0.5 * dur0 + 0.05, P0 * 1.005, 0.5, 100.0, 1.0 + rp0])

    def resid(th):
        return (y - _model(th, t, u, ss, exp)) / e

    # multi-start over impact parameter; keep the lowest χ²
    best = None
    for b0 in (0.1, 0.4, 0.7):
        x = x0.copy()
        x[4] = b0
        try:
            r = least_squares(resid, x, bounds=(lo, hi), x_scale=[0.01, 1e-4, 0.01, 1.0, 0.1], max_nfev=300)
        except Exception:
            continue
        if best is None or r.cost < best.cost:
            best = r
    if best is None:
        return {"ok": False, "reason": "Model fit failed to converge."}
    th = best.x
    chi2 = float(2 * best.cost)
    dof = max(len(t) - 5, 1)
    red = chi2 / dof
    # Parameter covariance from the Jacobian
    try:
        J = best.jac
        cov = np.linalg.pinv(J.T @ J) * max(red, 1.0)
        err = np.sqrt(np.clip(np.diag(cov), 0, None))
    except Exception:
        err = np.full(5, np.nan)
    names = ["t0", "period", "rp_rs", "a_rs", "b"]
    params = {n: {"value": float(v), "err": float(s), "method": "least-squares Jacobian"}
              for n, v, s in zip(names, th, err)}
    flags = []

    # Profile over the impact parameter: b, a/Rs and Rp/Rs are strongly degenerate for modest S/N, and
    # the Jacobian is meaningless when b sits at a bound. Refit the other parameters on a b grid and
    # report the Rp/Rs range allowed within Δχ² ≤ 1 (after scaling by the reduced χ²).
    prof_b, prof_chi, prof_rp = [], [], []
    for bg in np.linspace(0.0, min(0.95, 0.95), 8):
        def rb(x, bg=bg):
            return (y - _model([x[0], x[1], x[2], x[3], bg], t, u, ss, exp)) / e
        try:
            rr = least_squares(rb, [th[0], th[1], th[2], max(th[3], 2.0)],
                               bounds=(lo[:4], hi[:4]), x_scale=[0.01, 1e-4, 0.01, 1.0], max_nfev=120)
        except Exception:
            continue
        prof_b.append(float(bg)); prof_chi.append(float(2 * rr.cost)); prof_rp.append(float(rr.x[2]))
    prof_b.append(float(th[4])); prof_chi.append(float(chi2)); prof_rp.append(float(th[2]))  # the best fit itself
    if prof_chi:
        pc, pr = np.array(prof_chi), np.array(prof_rp)
        allowed = pc - min(pc.min(), chi2) <= max(red, 1.0)
        allowed[-1] = True
        rp_lo, rp_hi = float(pr[allowed].min()), float(pr[allowed].max())
        rp_lo, rp_hi = min(rp_lo, th[2]), max(rp_hi, th[2])
        half = 0.5 * (rp_hi - rp_lo)
        if half > params["rp_rs"]["err"]:
            params["rp_rs"]["err"] = float(half)
            params["rp_rs"]["method"] = "profile over impact parameter (Δχ²≤1) widened Jacobian error"
        params["rp_rs"]["range_over_b"] = [rp_lo, rp_hi]
    # Invalid Jacobian errors: report as unconstrained rather than a huge or tiny number
    for nme in ("a_rs", "b"):
        v, er = params[nme]["value"], params[nme]["err"]
        at_bound = (nme == "b" and v < 0.02) or not np.isfinite(er) or er > 3 * max(abs(v), 1.0) or (nme == "b" and er > 1.0)
        if at_bound:
            params[nme]["err"] = None
            params[nme]["method"] = "unconstrained by the data (degenerate with Rp/Rs and a/Rs); no error reported"
    if params["b"]["err"] is None or params["b"]["value"] > 0.85:
        flags.append("impact parameter is poorly constrained (b–a/Rs–Rp/Rs degeneracy); Rp/Rs uncertainty includes the range allowed over b")
    if red > 1.5:
        flags.append(f"reduced χ²={red:.2f} indicates unmodelled noise or detrending residuals; uncertainties were inflated by √χ²_red")
    if n_excluded:
        flags.append(f"{n_excluded} points inside other detected signals' transits were excluded from this fit")

    out: dict[str, Any] = {
        "ok": True, "params": params, "chi2": chi2, "dof": dof, "reduced_chi2": red,
        "n_points_fit": int(len(t)), "limb_darkening": {"u": list(u), "note": u_note, "fixed": True},
        "assumptions": ["circular orbit", "quadratic limb darkening fixed", "white Gaussian noise",
                        "no dilution/contamination correction", "single planet in the fit window"],
        "flags": flags,
        "supersample": {"factor": ss, "exp_time_days": exp},
    }
    # derived quantities
    rp, a, b, per = th[2], th[3], th[4], th[1]
    depth_model = float(1 - _model(th, np.array([th[0]]), u, 1, 0.0)[0])
    dur_tot = float(per / np.pi * np.arcsin(np.clip(np.sqrt((1 + rp) ** 2 - b ** 2) / (a * np.sqrt(1 - (b / a) ** 2)), 0, 1)))
    out["derived"] = {"depth_model_ppm": depth_model * 1e6, "duration_total_hours": dur_tot * 24,
                      "transit_depth_rp2_ppm": rp ** 2 * 1e6}
    # stellar density implied by a/Rs, for plausibility (circular orbit)
    rho = 3 * np.pi * a ** 3 / (G_CGS * (per * 86400) ** 2)
    out["derived"]["stellar_density_cgs"] = float(rho)
    out["derived"]["stellar_density_solar"] = float(rho / RHO_SUN)
    if star_radius_rsun and star_radius_rsun > 0:
        rp_e = rp * star_radius_rsun * R_SUN_IN_R_EARTH
        rel = (params["rp_rs"]["err"] or 0.0) / rp if rp > 0 else float("nan")
        rel_s = (star_radius_err / star_radius_rsun) if star_radius_err else 0.0
        err_e = rp_e * float(np.hypot(rel, rel_s))
        out["derived"]["planet_radius_earth"] = {"value": float(rp_e), "err": err_e,
                                                  "stellar_radius_rsun": star_radius_rsun,
                                                  "note": "Assumes no dilution; error combines fit and stellar radius uncertainty only."}
    else:
        out["derived"]["planet_radius_earth"] = None
        out["derived"]["radius_note"] = "Not computed: no stellar radius supplied. Only Rp/Rs is reported."

    if mcmc:
        try:
            out["mcmc"] = _run_mcmc(th, err, lo, hi, t, y, e, u, ss, exp, mcmc_steps, seed)
            # promote MCMC percentiles
            for n, q in out["mcmc"]["params"].items():
                params[n]["mcmc"] = q
        except Exception as ex:  # emcee missing or failure: keep the least-squares result
            out["mcmc"] = {"error": str(ex)}
    # best-fit curve for plotting on the whole (windowed) baseline
    out["_theta"] = th.tolist()
    out["_u"] = list(u)
    return out


def _run_mcmc(th, err, lo, hi, t, y, e, u, ss, exp, steps, seed):
    import emcee
    rng = np.random.default_rng(seed)
    ndim, nwalk = 5, 24
    scale = np.where(np.isfinite(err) & (err > 0), err, 1e-3)

    def lnp(x):
        if np.any(x < lo) or np.any(x > hi) or x[4] >= x[3]:
            return -np.inf
        r = (y - _model(x, t, u, ss, exp)) / e
        return -0.5 * float(r @ r)

    p0 = th + 0.3 * scale * rng.normal(size=(nwalk, ndim))
    p0 = np.clip(p0, lo + 1e-9, hi - 1e-9)
    sampler = emcee.EnsembleSampler(nwalk, ndim, lnp)
    sampler.run_mcmc(p0, steps, progress=False)
    burn = steps // 3
    chain = sampler.get_chain(discard=burn, flat=True)
    try:
        tau = sampler.get_autocorr_time(discard=burn, tol=0)
        tau_max = float(np.nanmax(tau))
    except Exception:
        tau_max = float("nan")
    names = ["t0", "period", "rp_rs", "a_rs", "b"]
    q = {n: {"p16": float(np.percentile(chain[:, i], 16)), "p50": float(np.percentile(chain[:, i], 50)),
             "p84": float(np.percentile(chain[:, i], 84))} for i, n in enumerate(names)}
    return {"params": q, "steps": steps, "walkers": nwalk, "burn_in": burn,
            "autocorr_time_max": tau_max,
            "converged": bool(np.isfinite(tau_max) and (steps - burn) > 50 * tau_max),
            "acceptance_fraction": float(np.mean(sampler.acceptance_fraction))}


def model_curve(theta, u, t, cadence_days):
    ss, exp = (7, cadence_days) if cadence_days > 10 / 1440 else (1, cadence_days)
    return _model(np.asarray(theta), np.asarray(t, float), u, ss, exp)
