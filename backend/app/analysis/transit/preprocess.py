"""Light-curve preprocessing for transit searches.

The original LightCurve is never modified; every step returns new arrays plus a record of what
was done (counts removed, window sizes) that is stored in the analysis provenance.

Detrending uses a time-windowed running median. Because any smoother can partially absorb real
transits, the pipeline runs a second pass in which points inside detected transits are masked
out of the trend estimate (and the trend is interpolated across them).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ...core.lightcurve import LightCurve, quality_masks


def _mad_sigma(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if len(x) < 5:
        return float("nan")
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def running_median_trend(time: np.ndarray, flux: np.ndarray, window_days: float,
                         mask: np.ndarray | None = None) -> np.ndarray:
    """Centered running median in a time window. Points with ``mask`` True are excluded from the
    estimate; the trend at those times is interpolated from the neighbouring unmasked trend."""
    use = np.ones(len(time), bool) if mask is None else ~mask
    s = pd.Series(flux[use], index=pd.to_datetime(time[use], unit="D"))
    trend_u = s.rolling(f"{int(window_days * 86400)}s", center=True, min_periods=5).median().to_numpy()
    good = np.isfinite(trend_u)
    if good.sum() < 2:
        return np.full(len(time), np.nanmedian(flux))
    return np.interp(time, time[use][good], trend_u[good])


def edge_distance(time: np.ndarray, gap_days: float) -> np.ndarray:
    """Distance (days) from each point to the nearest edge of its contiguous segment.
    Segments are split wherever consecutive samples are more than ``gap_days`` apart."""
    t = np.asarray(time)
    brk = np.where(np.diff(t) > gap_days)[0]
    starts = np.r_[0, brk + 1]
    ends = np.r_[brk, len(t) - 1]
    d = np.empty(len(t))
    for a, b in zip(starts, ends):
        seg = t[a:b + 1]
        d[a:b + 1] = np.minimum(seg - seg[0], seg[-1] - seg)
    return d


def clip_outliers(time, flux, upper_sigma=4.0, lower_sigma=7.0):
    """Remove high outliers, and *isolated* extreme low points (single-cadence glitches).

    A genuine transit spans many consecutive cadences, so a low point is only dropped when both
    neighbours are consistent with the local level.
    """
    sig = _mad_sigma(flux)
    med = np.median(flux)
    if not np.isfinite(sig) or sig == 0:
        return np.ones(len(flux), bool), 0
    z = (flux - med) / sig
    keep = z < upper_sigma
    low = z < -lower_sigma
    if low.any():
        idx = np.where(low)[0]
        for i in idx:
            left = z[i - 1] if i > 0 else 0.0
            right = z[i + 1] if i < len(z) - 1 else 0.0
            if left > -lower_sigma / 2 and right > -lower_sigma / 2:
                keep[i] = False
    return keep, int((~keep).sum())


def preprocess(lc: LightCurve, *, quality_mask: str = "default", detrend: bool = True,
               window_days: float | None = None, max_duration_days: float = 0.5,
               transit_mask: np.ndarray | None = None, clip: bool = True,
               bin_to_minutes: float | None = None) -> tuple[LightCurve, dict[str, Any]]:
    """Return a cleaned, normalised, detrended copy of ``lc`` and a record of the steps."""
    rec: dict[str, Any] = {"n_input": len(lc), "quality_mask": quality_mask}
    lc = lc.sorted()

    ok = np.isfinite(lc.time) & np.isfinite(lc.flux) & np.isfinite(lc.flux_err) & (lc.flux_err > 0)
    rec["removed_nonfinite"] = int((~ok).sum())
    if lc.quality is not None:
        bad = (lc.quality & quality_masks(lc.mission)[quality_mask]) != 0
        rec["removed_quality_flag"] = int((bad & ok).sum())
        ok &= ~bad
    else:
        rec["removed_quality_flag"] = 0
        rec["note_quality"] = "no quality column available; no flag-based filtering applied"
    keep_idx = np.where(ok)[0]
    work = lc.select(ok)
    t_mask_full = None if transit_mask is None else transit_mask[keep_idx]

    # duplicate timestamps break the time-windowed filters
    _, uniq = np.unique(work.time, return_index=True)
    if len(uniq) != len(work):
        rec["removed_duplicate_times"] = int(len(work) - len(uniq))
        work = work.select(np.isin(np.arange(len(work)), uniq))
        if t_mask_full is not None:
            t_mask_full = t_mask_full[np.isin(np.arange(len(t_mask_full)), uniq)]

    med = float(np.median(work.flux))
    if med <= 0:
        raise ValueError("Median flux is not positive; cannot normalise.")
    flux, err = work.flux / med, work.flux_err / med
    rec["normalisation_median"] = med

    if window_days is None:
        window_days = 0.75  # ≥ 3× a typical (≲6 h) transit; wider windows leave stellar variability in the data
    trend = np.ones_like(flux)
    if detrend and len(work) > 20:
        trend = running_median_trend(work.time, flux, window_days, t_mask_full)
        rec["detrend"] = {"method": "running median (time window)", "window_days": window_days,
                          "transit_masked": transit_mask is not None}
    else:
        rec["detrend"] = None
    flat = flux / trend
    err = err / trend

    if clip:
        keep, n_clipped = clip_outliers(work.time, flat)
        rec["removed_outliers"] = n_clipped
    else:
        keep = np.ones(len(flat), bool)
        rec["removed_outliers"] = 0
    # A one-sided window at a segment edge biases a running median on a sloped trend (up to ~1000 ppm
    # for 0.4% variability), producing periodic false dips. Trim W/2 from every segment edge.
    if detrend and len(work) > 20:
        edge = edge_distance(work.time, gap_days=max(0.2, 10 * float(np.median(np.diff(work.time)))))
        cut = edge < 0.5 * window_days
        rec["removed_edge_trim"] = int((cut & keep).sum())
        rec["edge_trim_days"] = 0.5 * window_days
        keep &= ~cut
    out = LightCurve(
        time=work.time[keep], flux=flat[keep], flux_err=err[keep], quality=None,
        time_format=work.time_format, time_offset_jd=work.time_offset_jd, mission=work.mission,
        meta=dict(work.meta, trend=trend[keep]),
    )
    out_mask = None if t_mask_full is None else t_mask_full[keep]
    if bin_to_minutes and out.median_cadence_days() * 1440 < bin_to_minutes * 0.7:
        out = bin_lightcurve(out, bin_to_minutes / 1440.0)
        rec["binned_to_minutes"] = bin_to_minutes
    rec["n_output"] = len(out)
    rec["scatter_ppm"] = float(_mad_sigma(out.flux) * 1e6)
    rec["median_cadence_min"] = float(out.median_cadence_days() * 1440)
    rec["baseline_days"] = out.baseline
    return out, rec


def bin_lightcurve(lc: LightCurve, width_days: float) -> LightCurve:
    edges = np.arange(lc.time.min(), lc.time.max() + width_days, width_days)
    idx = np.digitize(lc.time, edges)
    ts, fs, es = [], [], []
    for k in np.unique(idx):
        m = idx == k
        n = int(m.sum())
        if n < 2:
            # keep singletons only if they have close neighbours; otherwise they're noise in sparse regions
            pass
        w = 1.0 / lc.flux_err[m] ** 2
        ts.append(float(np.sum(lc.time[m] * w) / w.sum()))
        fs.append(float(np.sum(lc.flux[m] * w) / w.sum()))
        es.append(float(1.0 / np.sqrt(w.sum())))
    return LightCurve(time=np.array(ts), flux=np.array(fs), flux_err=np.array(es), quality=None,
                      time_format=lc.time_format, time_offset_jd=lc.time_offset_jd, mission=lc.mission,
                      meta={k: v for k, v in lc.meta.items() if k != "trend"})
