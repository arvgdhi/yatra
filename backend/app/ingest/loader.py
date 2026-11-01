"""Convert a profiled table into the shared LightCurve model (never touches the source file)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..core.lightcurve import LightCurve
from .profiler import TIME_UNIT_TO_DAYS, build_profile
from .reader import IngestError, RawTable, read_table


def load_lightcurve(path: Path, mapping: dict[str, Any] | None = None,
                    table: RawTable | None = None) -> tuple[LightCurve, dict[str, Any]]:
    """Return (LightCurve, profile). Raises IngestError when the data cannot be a light curve."""
    table = table or read_table(path)
    profile = build_profile(table, mapping)
    roles = profile["roles"]
    if "time" not in roles or "flux" not in roles:
        raise IngestError("A time column and a flux column are required for a light curve.",
                          "Use the column-mapping form to choose them.")
    cols = table.columns
    time_info = profile["time"] or {}
    t = cols[roles["time"]["column"]].astype(float) * time_info.get("to_days", 1.0)
    f = cols[roles["flux"]["column"]].astype(float)
    e = (cols[roles["flux_err"]["column"]].astype(float) if "flux_err" in roles
         else np.full_like(f, np.nan))
    q = (np.nan_to_num(cols[roles["quality"]["column"]].astype(float), nan=0).astype(np.int64)
         if "quality" in roles else None)

    kind = profile["flux_kind"]
    if kind == "magnitude":
        # m = -2.5 log10(F)  ->  F_rel = 10^(-0.4 (m - m_med)),  sigma_F/F = 0.921 sigma_m
        med = np.nanmedian(f)
        rel = 10 ** (-0.4 * (f - med))
        e = rel * 0.4 * np.log(10) * e if "flux_err" in roles else np.full_like(rel, np.nan)
        f = rel
    elif kind in ("counts", "unknown", None):
        med = np.nanmedian(f)
        if not np.isfinite(med) or med == 0:
            raise IngestError("Cannot normalise flux: median is zero or undefined.")
        f, e = f / med, e / med
    # relative flux is left as is

    if "flux_err" not in roles or not np.isfinite(e).any():
        # Empirical uncertainty from point-to-point scatter, flagged in the profile.
        ok = np.isfinite(f)
        sig = 1.4826 * np.nanmedian(np.abs(np.diff(f[ok]))) / np.sqrt(2) if ok.sum() > 3 else 1e-3
        e = np.full_like(f, max(sig, 1e-6))
        profile["quality_issues"].append({"severity": "warning",
                                          "text": f"No flux uncertainties: using empirical point-to-point scatter {sig:.2e}"})
        profile["uncertainties_estimated"] = True

    fmt = time_info.get("format", "relative")
    off = time_info.get("offset_jd")
    lc = LightCurve(time=t, flux=f, flux_err=e, quality=q, time_format=fmt, time_offset_jd=off,
                    mission=table.header.get("mission"),
                    meta={"header": table.header, "flux_kind": kind,
                          "time_column": roles["time"]["column"], "flux_column": roles["flux"]["column"]})
    return lc, profile
