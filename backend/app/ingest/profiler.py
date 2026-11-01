"""Dataset profiling: infer measurement type from several independent lines of evidence.

The result is a plain dict (JSON-serialisable) so it can be stored with the dataset, shown in the
UI, and recorded in the analysis provenance. Classification never relies on a single column name:
each category accumulates weighted evidence, ambiguity is reported, and users can override the
column mapping and conventions (``mapping``), after which the profile is recomputed.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .columns import (ROLE_ALIASES, WEAK_ALIASES, infer_time_format, is_magnitude, match_roles, norm)
from .reader import RawTable

CATEGORIES = [
    "photometric_time_series", "radial_velocity", "spectroscopy", "image", "astrometry", "unknown",
]
CATEGORY_LABELS = {
    "photometric_time_series": "Photometric time series",
    "radial_velocity": "Radial velocity measurements",
    "spectroscopy": "Spectroscopic observations",
    "image": "Astronomical image / cube",
    "astrometry": "Astrometric measurements",
    "unknown": "Unknown / unsupported",
}
TIME_UNIT_TO_DAYS = {"d": 1.0, "day": 1.0, "days": 1.0, "h": 1 / 24, "hour": 1 / 24, "hours": 1 / 24,
                     "min": 1 / 1440, "minutes": 1 / 1440, "s": 1 / 86400, "sec": 1 / 86400, "seconds": 1 / 86400}

# What each category can be analysed with, and whether that module actually exists.
METHODS = {
    "photometric_time_series": [
        {"id": "transit_bls", "name": "Transit search (BLS) + model fit", "status": "available"},
    ],
    "radial_velocity": [
        {"id": "rv_periodogram", "name": "RV periodogram + Keplerian fit", "status": "planned"},
    ],
    "spectroscopy": [
        {"id": "transmission_spectroscopy", "name": "Atmospheric characterisation", "status": "planned"},
    ],
    "image": [
        {"id": "direct_imaging", "name": "Direct-imaging PSF subtraction", "status": "planned"},
    ],
    "astrometry": [
        {"id": "astrometric_orbit", "name": "Astrometric orbit fit", "status": "planned"},
    ],
    "unknown": [],
}


def _numeric(arr: np.ndarray) -> bool:
    return arr.dtype.kind in "iuf"


def _pick(cands: list[tuple[str, int]], cols: dict[str, np.ndarray], used: set[str]) -> tuple[str, list[str]] | None:
    """Choose a numeric, not-yet-used candidate; return (column, alternatives)."""
    ok = [c for c, _ in cands if c in cols and _numeric(cols[c]) and c not in used]
    if not ok:
        return None
    return ok[0], ok[1:]


def build_profile(table: RawTable, mapping: dict[str, Any] | None = None) -> dict[str, Any]:
    mapping = mapping or {}
    cols = table.columns
    names = list(cols)
    evidence: list[dict[str, str]] = []
    issues: list[dict[str, str]] = []

    def ev(kind: str, text: str):
        evidence.append({"kind": kind, "text": text})

    def issue(severity: str, text: str):
        issues.append({"severity": severity, "text": text})

    profile: dict[str, Any] = {
        "file_format": table.file_format, "n_rows": table.n_rows, "header": table.header,
        "n_columns": len(names), "columns_found": names, "notes": list(table.notes),
        "mapping_applied": mapping,
    }

    # ---- image-only FITS ---------------------------------------------------------------
    if table.file_format == "fits" and not cols:
        ev("fits", "FITS file has no table extension with rows (only image/cube HDUs)")
        profile.update(_finish("image", 0.8, [], evidence, issues, {}, {}, None, table))
        profile["fits_info"] = table.fits_info
        return profile

    if not cols:
        issue("error", "No readable columns were found.")
        profile.update(_finish("unknown", 0.0, [], evidence, issues, {}, {}, None, table))
        return profile

    # ---- role detection ----------------------------------------------------------------
    cand = match_roles(names)
    roles: dict[str, dict[str, Any]] = {}
    used: set[str] = set()
    # explicit user mapping wins
    for role, col in mapping.items():
        if role in ROLE_ALIASES and col in cols:
            roles[role] = {"column": col, "source": "user", "alternatives": [], "unit": table.units.get(col)}
            used.add(col)
    for role in ["time", "flux", "flux_err", "quality", "rv", "rv_err", "wavelength", "ra", "dec",
                 "ra_err", "dec_err"]:
        if role in roles:
            continue
        if role not in cand:
            continue
        pick = _pick(cand[role], cols, used)
        if pick:
            col, alts = pick
            weak = norm(col) in WEAK_ALIASES
            roles[role] = {"column": col, "source": "alias-weak" if weak else "alias", "alternatives": alts,
                           "unit": table.units.get(col)}
            used.add(col)
            ev("columns", f"column '{col}' matches the {role} alias list" + (" (weak: short/generic name)" if weak else ""))

    # FITS table: prefer PDCSAP over SAP if both are present, and say so
    if table.file_format == "fits" and "flux" in roles:
        alts = roles["flux"]["alternatives"]
        if roles["flux"]["column"].upper() == "PDCSAP_FLUX":
            ev("fits", "PDCSAP_FLUX available: systematics-corrected flux preferred over SAP_FLUX")
        elif alts:
            issue("info", f"Multiple flux columns detected ({roles['flux']['column']}, {', '.join(alts)}); using the first")

    # ---- per-role numeric diagnostics -----------------------------------------------------
    diag: dict[str, Any] = {}
    for role, r in roles.items():
        a = cols[r["column"]].astype(float)
        fin = np.isfinite(a)
        diag[role] = {"finite_fraction": float(fin.mean()) if len(a) else 0.0}
        if fin.any():
            diag[role].update({"min": float(a[fin].min()), "max": float(a[fin].max()),
                               "median": float(np.median(a[fin]))})
        if diag[role]["finite_fraction"] < 0.5:
            issue("warning", f"{role} column '{r['column']}' is more than 50% missing/non-numeric")

    # ---- time conventions -----------------------------------------------------------------
    time_info = None
    if "time" in roles:
        t = cols[roles["time"]["column"]].astype(float)
        hints = dict(table.header)
        time_info = infer_time_format(roles["time"]["column"], t, hints)
        if table.file_format == "fits":
            bi, bf = table.header.get("bjdrefi"), table.header.get("bjdreff")
            if bi is not None:
                time_info["offset_jd"] = float(bi) + float(bf or 0.0)
                time_info["format"] = "bjd-ref"
                time_info["confidence"] = 0.95
                time_info["evidence"].append(f"header BJDREFI/BJDREFF give reference epoch {time_info['offset_jd']}")
        for e in time_info["evidence"]:
            ev("time", e)
        unit = (mapping.get("time_unit") or roles["time"].get("unit") or table.header.get("timeunit") or "d")
        factor = TIME_UNIT_TO_DAYS.get(str(unit).strip().lower())
        if factor is None:
            issue("warning", f"time unit '{unit}' not recognised; assuming days. Override if wrong.")
            factor = 1.0
        time_info["unit"] = unit
        time_info["to_days"] = factor
        if "time_format" in mapping:
            time_info["format"] = mapping["time_format"]

    # ---- flux conventions -------------------------------------------------------------------
    flux_kind = None
    if "flux" in roles:
        f = cols[roles["flux"]["column"]].astype(float)
        ff = f[np.isfinite(f)]
        unit = roles["flux"].get("unit")
        if mapping.get("flux_kind"):
            flux_kind = mapping["flux_kind"]
            ev("flux", f"flux convention set by user: {flux_kind}")
        elif is_magnitude(roles["flux"]["column"], f, unit):
            flux_kind = "magnitude"
            ev("flux", "flux column looks like magnitudes (name/unit); will be converted to relative flux")
        elif len(ff):
            med = float(np.median(ff))
            if 0.5 < med < 1.5 and np.nanstd(ff) < 0.5:
                flux_kind = "relative"
                ev("flux", f"flux median {med:.4g} with small scatter: already normalised")
            elif med > 0:
                flux_kind = "counts"
                ev("flux", f"flux median {med:.4g}: absolute counts/rate, will be normalised by the median")
            else:
                flux_kind = "unknown"
                issue("warning", "flux median is not positive; flux convention is unclear (magnitudes? differential flux?)")
        if len(ff) and (ff <= 0).mean() > 0.01 and flux_kind != "magnitude":
            issue("warning", f"{(ff <= 0).mean():.1%} of flux values are non-positive")

    # ---- category scoring ---------------------------------------------------------------------
    s = {c: 0.0 for c in CATEGORIES if c != "unknown"}
    has = lambda r: r in roles
    if has("time") and has("flux"):
        s["photometric_time_series"] += 0.55
        ev("classification", "has a time column and a flux column")
        if has("flux_err"):
            s["photometric_time_series"] += 0.12
        if has("quality"):
            s["photometric_time_series"] += 0.08
        if flux_kind in ("relative", "counts"):
            s["photometric_time_series"] += 0.08
        if table.header.get("mission") in ("tess", "kepler", "k2"):
            s["photometric_time_series"] += 0.12
            ev("classification", f"mission keyword '{table.header['mission']}' in FITS header")
        if table.header.get("extname", "").upper() == "LIGHTCURVE":
            s["photometric_time_series"] += 0.1
            ev("classification", "FITS extension is named LIGHTCURVE")
        if has("wavelength"):
            s["photometric_time_series"] -= 0.15
    if has("time") and has("rv"):
        s["radial_velocity"] += 0.6
        ev("classification", "has a time column and a radial-velocity column")
        if has("rv_err"):
            s["radial_velocity"] += 0.15
        r = diag.get("rv", {})
        if r.get("max") is not None and r["max"] - r["min"] > 0:
            if (r["max"] - r["min"]) < 1e5:
                s["radial_velocity"] += 0.05
    if has("wavelength") and has("flux") and not has("time"):
        s["spectroscopy"] += 0.65
        ev("classification", "has wavelength and flux columns but no time column: spectrum-like")
        w = cols[roles["wavelength"]["column"]].astype(float)
        w = w[np.isfinite(w)]
        if len(w) > 10 and (np.all(np.diff(w) > 0) or np.all(np.diff(w) < 0)):
            s["spectroscopy"] += 0.15
            ev("classification", "wavelength axis is monotonic")
    elif has("wavelength") and has("flux") and has("time"):
        s["spectroscopy"] += 0.3
        ev("classification", "wavelength present alongside time: could be a time-resolved spectrum")
    if has("time") and has("ra") and has("dec"):
        s["astrometry"] += 0.6
        ev("classification", "has time plus sky-position columns (RA/Dec)")
        if has("ra_err") or has("dec_err"):
            s["astrometry"] += 0.15
    elif has("ra") and has("dec") and not has("flux"):
        s["astrometry"] += 0.3
        ev("classification", "sky positions without time: catalogue-like, not an astrometric time series")

    # a weak-alias-only match is not enough to trust a category
    for cat, needed in (("photometric_time_series", ("time", "flux")), ("radial_velocity", ("time", "rv"))):
        if all(has(n) for n in needed) and all(roles[n]["source"] == "alias-weak" for n in needed):
            s[cat] = min(s[cat], 0.45)
            issue("warning", "classification relies on generic column names only; please confirm the mapping")

    ranked = sorted(s.items(), key=lambda kv: -kv[1])
    top, top_score = ranked[0]
    second, second_score = ranked[1]
    if top_score < 0.4:
        top, top_score = "unknown", 0.0
        ev("classification", "no category reached the minimum evidence threshold")
    confidence = float(min(top_score, 1.0))
    alternatives = [{"category": c, "label": CATEGORY_LABELS[c], "score": round(v, 3)}
                    for c, v in ranked if v >= 0.3 and c != top]
    ambiguous = bool(top != "unknown" and second_score >= 0.4 and top_score - second_score < 0.2)

    cov = _coverage(cols, roles, time_info, mapping) if top == "photometric_time_series" else None
    profile.update(_finish(top, confidence, alternatives, evidence, issues, roles, diag, time_info, table,
                           flux_kind=flux_kind, ambiguous=ambiguous, coverage=cov))
    return profile


def _coverage(cols, roles, time_info, mapping) -> dict[str, Any]:
    t = cols[roles["time"]["column"]].astype(float) * (time_info or {}).get("to_days", 1.0)
    f = cols[roles["flux"]["column"]].astype(float)
    valid = np.isfinite(t) & np.isfinite(f)
    tv = np.sort(t[valid])
    out: dict[str, Any] = {"n_rows": int(len(t)), "n_valid": int(valid.sum())}
    if len(tv) < 2:
        return out
    dt = np.diff(tv)
    cad = float(np.median(dt))
    gaps = np.where(dt > max(5 * cad, 0.5))[0]
    out.update({
        "time_start": float(tv[0]), "time_end": float(tv[-1]), "baseline_days": float(tv[-1] - tv[0]),
        "median_cadence_s": cad * 86400.0, "n_gaps": int(len(gaps)),
        "largest_gap_days": float(dt.max()),
        "duty_cycle": float(min(1.0, len(tv) * cad / max(tv[-1] - tv[0], 1e-9))),
        "duplicate_times": int(len(tv) - len(np.unique(tv))),
        "sorted": bool(np.all(np.diff(t[valid]) >= 0)),
    })
    return out


def _finish(category, confidence, alternatives, evidence, issues, roles, diag, time_info, table,
            flux_kind=None, ambiguous=False, coverage=None) -> dict[str, Any]:
    methods = [dict(m) for m in METHODS[category]]
    limitations: list[str] = []
    needs_confirmation = ambiguous or (0 < confidence < 0.6) or (category == "unknown" and bool(table.columns))
    if any("no header row" in n for n in table.notes):
        issues.append({"severity": "warning",
                       "text": "The file has no header row, so columns could not be identified by name. "
                               "Assign time/flux/uncertainty columns (and the time unit) in the mapping form."})
    for m in methods:
        if m["status"] != "available":
            m["reason"] = "Module is planned but not yet implemented."
            continue
        if m["id"] == "transit_bls":
            ok, reason = _transit_ok(coverage, roles, issues)
            if not ok:
                m["status"] = "unsuitable"
            m["reason"] = reason
    if category == "unknown":
        limitations.append("The file could not be matched to a supported measurement type. "
                           "Use the column-mapping form to assign time/flux columns, or upload a "
                           "light curve (CSV/FITS) with time and flux columns.")
    elif all(m["status"] == "planned" for m in methods):
        limitations.append(f"{CATEGORY_LABELS[category]} were recognised, but no analysis module is implemented yet; "
                           "the data can be inspected but not analysed.")
    if flux_kind == "magnitude":
        limitations.append("Magnitudes are converted to relative flux; error propagation assumes small errors.")
    if time_info and time_info.get("format") == "relative":
        limitations.append("Time has no absolute reference; epochs are reported relative to the first observation.")
    return {
        "category": category, "category_label": CATEGORY_LABELS[category],
        "confidence": round(confidence, 3), "ambiguous": ambiguous,
        "needs_confirmation": needs_confirmation, "alternatives": alternatives,
        "evidence": evidence, "roles": roles, "column_diagnostics": diag, "time": time_info,
        "flux_kind": flux_kind, "quality_issues": issues, "coverage": coverage,
        "applicable_methods": methods, "limitations": limitations,
    }


def _transit_ok(cov, roles, issues) -> tuple[bool, str]:
    if cov is None or cov.get("n_valid", 0) == 0:
        return False, "No usable time/flux data."
    if cov["n_valid"] < 200:
        return False, f"Only {cov['n_valid']} valid points; at least 200 are needed for a meaningful transit search."
    if cov.get("baseline_days", 0) < 1.0:
        return False, "Observation baseline is shorter than one day, which cannot constrain a periodic signal."
    cad = cov.get("median_cadence_s", 0)
    if cad and cad > 3600 * 6:
        return False, f"Median cadence {cad / 3600:.1f} h is too sparse to resolve typical transits."
    return True, "Time series with sufficient length and cadence for a Box Least Squares search."
