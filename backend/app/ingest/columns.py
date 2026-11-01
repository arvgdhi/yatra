"""Column alias tables and unit/time-convention inference.

Aliases are matched on a normalised name (lower-case, non-alphanumerics stripped). Nothing here
silently decides: the profiler reports which alias matched so the user can override it.
"""
from __future__ import annotations

import re

import numpy as np


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


# role -> normalised aliases, in priority order (earlier = preferred)
ROLE_ALIASES: dict[str, list[str]] = {
    "time": ["time", "bjd", "bjdtdb", "btjd", "bkjd", "jd", "hjd", "mjd", "bmjd", "bjdmid", "timebjd",
             "timebtjd", "timebkjd", "barytime", "t", "timestamp", "epoch", "date", "obstime",
             "timemid", "timejd", "timemjd"],
    "flux": ["pdcsapflux", "sapflux", "flux", "fluxnorm", "normflux", "normalizedflux", "relflux",
             "rflux", "fluxdetrended", "detrendedflux", "fluxflat", "flatflux", "fluxcorr",
             "fluxpdcsap", "fluxsap", "kspsapflux", "magnitude", "mag", "dflux", "fluxmean",
             "fluxmedian", "brightness", "counts", "f"],
    "flux_err": ["pdcsapfluxerr", "sapfluxerr", "fluxerr", "fluxerror", "fluxunc", "eflux", "errflux",
                 "ferr", "err", "error", "uncertainty", "sigma", "sigmaflux", "dfluxerr", "magerr",
                 "e", "fluxerrnorm", "pdcsapfluxerror"],
    "quality": ["qualityflag", "quality", "qflag", "dq", "flags", "flag", "sapquality"],
    # radial velocity
    "rv": ["rv", "vrad", "radialvelocity", "rvkms", "rvms", "vr", "velocity", "rvobs", "rvmean", "mnvel"],
    "rv_err": ["rverr", "svrad", "rverror", "evrad", "erv", "radialvelocityerr", "sigmarv", "errvel",
               "rvunc", "rvuncertainty", "errvr"],
    # spectroscopy
    "wavelength": ["wavelength", "wave", "lambda", "wl", "lam", "wavelengthangstrom", "waveang",
                   "wavenm", "waveum", "wavelen", "wavenumber", "freq", "frequency"],
    # astrometry / positions
    "ra": ["ra", "rade", "raj2000", "rajd", "raicrs", "raoffset", "dra", "rastar"],
    "dec": ["dec", "decj2000", "decjd", "decicrs", "decoffset", "ddec", "decstar", "de"],
    "ra_err": ["raerr", "eera", "raerror", "draerr", "raunc"],
    "dec_err": ["decerr", "eedec", "decerror", "ddecerr", "decunc"],
}

# Aliases that are ambiguous on their own and shouldn't be trusted without corroboration.
WEAK_ALIASES = {"t", "f", "e", "err", "error", "flag", "date", "epoch", "counts", "brightness", "sigma",
                "de", "mag", "magnitude"}

TIME_FORMAT_HINTS = {
    "btjd": ("btjd", 2457000.0), "timebtjd": ("btjd", 2457000.0),
    "bkjd": ("bkjd", 2454833.0), "timebkjd": ("bkjd", 2454833.0),
    "mjd": ("mjd", 2400000.5), "bmjd": ("mjd", 2400000.5), "timemjd": ("mjd", 2400000.5),
    "bjd": ("bjd", 0.0), "bjdtdb": ("bjd", 0.0), "hjd": ("hjd", 0.0), "jd": ("jd", 0.0),
    "timejd": ("jd", 0.0), "bjdmid": ("bjd", 0.0), "timebjd": ("bjd", 0.0),
}


def match_roles(columns: list[str]) -> dict[str, list[tuple[str, int]]]:
    """For each role return candidate (column, priority) pairs; lower priority = better."""
    normed = {c: norm(c) for c in columns}
    out: dict[str, list[tuple[str, int]]] = {}
    for role, aliases in ROLE_ALIASES.items():
        hits: list[tuple[str, int]] = []
        for col, n in normed.items():
            if n in aliases:
                hits.append((col, aliases.index(n)))
        hits.sort(key=lambda x: x[1])
        if hits:
            out[role] = hits
    return out


def infer_time_format(col_name: str, values: np.ndarray, header_hints: dict | None = None) -> dict:
    """Infer the time convention from the name, magnitude and header keywords.

    Returns {format, offset_jd, confidence, evidence}. Offsets are only claimed when the evidence
    supports them; otherwise the series is treated as relative time (period search still works).
    """
    n = norm(col_name)
    ev: list[str] = []
    fmt, off, conf = "relative", None, 0.3
    if n in TIME_FORMAT_HINTS:
        fmt, off = TIME_FORMAT_HINTS[n]
        conf = 0.85
        ev.append(f"column name '{col_name}' implies {fmt.upper()}")
    finite = values[np.isfinite(values)]
    if len(finite):
        med = float(np.median(finite))
        if fmt == "relative":
            if 2_400_000 < med < 2_700_000:
                fmt, off, conf = "jd", 0.0, 0.7
                ev.append(f"values ~{med:.1f} fall in the Julian Date range")
            elif 50_000 < med < 70_000:
                fmt, off, conf = "mjd", MJD_OFFSET_JD, 0.6
                ev.append(f"values ~{med:.1f} fall in the Modified Julian Date range")
            elif 1_000 < med < 3_500 and header_hints and header_hints.get("mission") == "tess":
                fmt, off, conf = "btjd", 2457000.0, 0.7
                ev.append("TESS mission with values in BTJD range")
            elif 100 < med < 2_000 and header_hints and header_hints.get("mission") in ("kepler", "k2"):
                fmt, off, conf = "bkjd", 2454833.0, 0.7
                ev.append("Kepler mission with values in BKJD range")
            else:
                ev.append("no absolute time reference recognised; treating time as relative days")
        else:
            # sanity-check the claimed format against the magnitude
            expected = {"btjd": (1_000, 4_500), "bkjd": (100, 2_000), "mjd": (40_000, 80_000),
                        "jd": (2_400_000, 2_700_000), "bjd": (2_400_000, 2_700_000),
                        "hjd": (2_400_000, 2_700_000)}.get(fmt)
            if expected and not (expected[0] <= med <= expected[1]):
                ev.append(f"warning: median {med:.1f} outside typical {fmt.upper()} range {expected}")
                conf = min(conf, 0.5)
    if header_hints:
        if header_hints.get("timesys"):
            ev.append(f"header TIMESYS={header_hints['timesys']}")
        if header_hints.get("timeunit") and str(header_hints["timeunit"]).lower() not in ("d", "day", "days"):
            ev.append(f"warning: header TIMEUNIT={header_hints['timeunit']} is not days; conversion required")
    return {"format": fmt, "offset_jd": off, "confidence": conf, "evidence": ev}


MJD_OFFSET_JD = 2400000.5


def is_magnitude(col_name: str, values: np.ndarray, unit: str | None) -> bool:
    n = norm(col_name)
    if n in ("mag", "magnitude", "magerr") or (unit and unit.lower().startswith("mag")):
        return True
    return False
