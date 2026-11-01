"""Automated false-positive / artifact checks for a BLS candidate.

These are *screening* heuristics. Passing every check does not validate a planet; failing a
check is a reason for caution, not proof of a false positive. Each check reports its inputs so a
reader can judge it.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ...core.lightcurve import LightCurve


def _pair(x) -> tuple[float, float]:
    """astropy returns (value, uncertainty) tuples for several stats."""
    try:
        return float(x[0]), float(x[1])
    except (TypeError, IndexError):
        return float(x), float("nan")


def check(id_: str, status: str, detail: str, **values) -> dict[str, Any]:
    return {"id": id_, "status": status, "detail": detail, "values": values}


def vet_candidate(cand: dict[str, Any], lc: LightCurve, other_candidates: list[dict[str, Any]],
                  *, sde_threshold: float = 8.5, min_depth_snr: float = 7.1, known_planets: list[dict] | None = None) -> dict[str, Any]:
    stats = cand["_stats"]
    P, dur, depth = cand["period"], cand["duration"], cand["depth"]
    checks: list[dict[str, Any]] = []

    # 1. significance
    s = cand["sde"]
    checks.append(check("sde", "pass" if s >= sde_threshold else "fail",
                        f"SDE {s:.1f} vs threshold {sde_threshold:g}", sde=s, threshold=sde_threshold))
    snr = cand["depth_snr"]
    checks.append(check("depth_snr", "pass" if snr >= min_depth_snr else ("warn" if snr >= 5 else "fail"),
                        f"Box depth S/N {snr:.1f} vs threshold {min_depth_snr:g}", depth_snr=snr))

    # 2. number of transits
    counts = np.asarray(stats["per_transit_count"])
    n_obs = int((counts > 0).sum())
    expected = len(counts)
    checks.append(check("n_transits", "pass" if n_obs >= 3 else ("warn" if n_obs == 2 else "fail"),
                        f"{n_obs} transit(s) with data out of {expected} within the baseline", observed=n_obs, scheduled=expected))
    if expected and n_obs < expected:
        frac = 1 - n_obs / expected
        if frac > 0.3:
            checks.append(check("coverage_gaps", "warn",
                                f"{frac:.0%} of scheduled transits fall in data gaps", fraction_missing=frac))

    # 3. single-event dominance
    ll = np.asarray(stats["per_transit_log_likelihood"], float)
    ll = ll[np.isfinite(ll)]
    pos = ll[ll > 0]
    if len(pos) >= 1 and pos.sum() > 0:
        dom = float(pos.max() / pos.sum())
        status = "pass" if (dom < 0.5 or n_obs <= 1) else "fail" if dom > 0.75 else "warn"
        if n_obs >= 2:
            checks.append(check("single_event_dominance", status,
                                f"Strongest single transit contributes {dom:.0%} of the signal", fraction=dom))
    # 4. odd/even depth
    do, de = _pair(stats["depth_odd"]), _pair(stats["depth_even"])
    if np.isfinite(do[1]) and np.isfinite(de[1]) and n_obs >= 4:
        sig = abs(do[0] - de[0]) / np.hypot(do[1], de[1])
        checks.append(check("odd_even", "pass" if sig < 3 else ("warn" if sig < 5 else "fail"),
                            f"Odd/even depth differ by {sig:.1f}σ (odd {do[0] * 1e6:.0f} ppm, even {de[0] * 1e6:.0f} ppm); "
                            "a large difference suggests an eclipsing binary at twice the period",
                            sigma=float(sig), odd_ppm=do[0] * 1e6, even_ppm=de[0] * 1e6))
    else:
        checks.append(check("odd_even", "na", "Too few transits to compare odd and even depths"))
    # 5. secondary eclipse at phase 0.5
    dp = _pair(stats["depth_phased"])
    if np.isfinite(dp[1]) and dp[1] > 0:
        sig = dp[0] / dp[1]
        frac = dp[0] / depth if depth > 0 else float("nan")
        bad = sig > 3 and frac > 0.3
        checks.append(check("secondary_eclipse", "fail" if bad else ("warn" if sig > 3 else "pass"),
                            f"Depth at phase 0.5: {dp[0] * 1e6:.0f} ± {dp[1] * 1e6:.0f} ppm ({sig:.1f}σ)"
                            + ("; a comparable secondary suggests an eclipsing binary" if bad else ""),
                            sigma=float(sig), depth_ppm=dp[0] * 1e6))
    # 6. sinusoidal alternative
    hd = float(stats["harmonic_delta_log_likelihood"])
    checks.append(check("sinusoid_alternative", "warn" if hd > 0 else "pass",
                        ("A sinusoid at this period fits better than a box: likely stellar variability or "
                         "ellipsoidal modulation" if hd > 0 else "A box fits better than a sinusoid at this period"),
                        delta_log_likelihood=hd))
    # 7. depth plausibility
    if depth > 0.15:
        checks.append(check("depth_size", "warn", f"Depth {depth * 100:.1f}% is too deep for most planets; "
                            "consider an eclipsing binary or blend", depth=depth))
    else:
        checks.append(check("depth_size", "pass", f"Depth {depth * 1e6:.0f} ppm", depth=depth))
    # 8. duration plausibility (geometry only: a planet's transit lasts ≲ P/π for a circular orbit
    #    around a star with ρ ≳ 0.1 ρ☉ at central transit)
    max_dur = P / np.pi
    checks.append(check("duration_vs_period", "pass" if dur <= max_dur else "fail",
                        f"Duration {dur * 24:.2f} h vs geometric ceiling {max_dur * 24:.1f} h for P={P:.2f} d",
                        duration_hours=dur * 24))
    # 9. alias / harmonic of another candidate
    for o in other_candidates:
        if o is cand:
            continue
        r = P / o["period"]
        for num, den in [(1, 2), (2, 1), (1, 3), (3, 1), (2, 3), (3, 2)]:
            if abs(r - num / den) < 0.01 * (num / den):
                checks.append(check("alias_of_other_candidate", "warn",
                                    f"Period ratio to candidate {o['rank']} is {num}:{den}; "
                                    "may be an alias or harmonic of the same signal",
                                    other_rank=o["rank"], ratio=f"{num}:{den}"))
                break
    # 10. cadence sanity: duration should span several cadences
    cad = lc.median_cadence_days()
    if np.isfinite(cad) and dur < 2 * cad:
        checks.append(check("duration_vs_cadence", "warn",
                            f"Duration {dur * 24:.2f} h is only {dur / cad:.1f} cadences", n_cadences=dur / cad))

    # classification relative to the catalogue
    match = None
    for kp in known_planets or []:
        kp_per = kp.get("period")
        if kp_per and abs(P - kp_per) / kp_per < 0.02:
            match = kp
            break
        if kp_per:
            for ratio in (0.5, 2.0):
                if abs(P - kp_per * ratio) / (kp_per * ratio) < 0.01:
                    match = dict(kp, alias_ratio=ratio)
                    break
    n_fail = sum(c["status"] == "fail" for c in checks)
    n_warn = sum(c["status"] == "warn" for c in checks)
    return {"checks": checks, "n_fail": n_fail, "n_warn": n_warn, "catalog_match": match}
