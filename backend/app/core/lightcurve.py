"""Shared in-memory data model for photometric time series.

Every entry point (uploaded file, archive product) is converted to this structure before
analysis. The original file on disk is never modified.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

# Reference epochs (JD) for mission-specific time systems.
BTJD_OFFSET = 2457000.0          # TESS: BJD - 2457000
BKJD_OFFSET = 2454833.0          # Kepler/K2: BJD - 2454833
MJD_OFFSET = 2400000.5


# --- Quality flags -----------------------------------------------------------------------
# Bit definitions and default masks mirror Lightkurve's QualityFlags classes (read from its
# source, v2.x). The default masks drop cadences that are known to be unreliable while
# keeping cadences flagged only for e.g. cosmic-ray mitigation or scattered light.
class TessQuality:
    AttitudeTweak = 1
    SafeMode = 2
    CoarsePoint = 4
    EarthPoint = 8
    Argabrightening = 16
    Desat = 32
    ApertureCosmic = 64
    ManualExclude = 128
    Discontinuity = 256
    ImpulsiveOutlier = 512
    CollateralCosmic = 1024
    Straylight = 2048
    PlanetSearchExclude = 8192
    BadCalibrationExclude = 16384
    InsufficientTargets = 32768

    DEFAULT = (AttitudeTweak | SafeMode | CoarsePoint | EarthPoint | Argabrightening | Desat
               | ManualExclude | ImpulsiveOutlier | BadCalibrationExclude)
    HARD = DEFAULT | ApertureCosmic | CollateralCosmic | Straylight
    HARDEST = 65535


class KeplerQuality:
    AttitudeTweak = 1
    SafeMode = 2
    CoarsePoint = 4
    EarthPoint = 8
    ZeroCrossing = 16
    Desat = 32
    Argabrightening = 64
    ApertureCosmic = 128
    ManualExclude = 256
    SensitivityDropout = 1024
    ImpulsiveOutlier = 2048
    ArgabrighteningOnCCD = 4096
    CollateralCosmic = 8192
    DetectorAnomaly = 16384
    NoFinePoint = 32768
    NoData = 65536
    RollingBandInAperture = 131072
    RollingBandInMask = 262144
    PossibleThrusterFiring = 524288
    ThrusterFiring = 1048576

    DEFAULT = (AttitudeTweak | SafeMode | CoarsePoint | EarthPoint | Desat | ManualExclude
               | DetectorAnomaly | NoData | ThrusterFiring)
    HARD = DEFAULT | SensitivityDropout | ApertureCosmic | CollateralCosmic | PossibleThrusterFiring
    HARDEST = 2096639


def quality_masks(mission: str | None) -> dict[str, int]:
    """Named bitmasks for a mission. Unknown missions get TESS-style masks only if flagged."""
    m = (mission or "").lower()
    if m in ("kepler", "k2"):
        q = KeplerQuality
    else:
        q = TessQuality
    return {"none": 0, "default": q.DEFAULT, "hard": q.HARD, "hardest": q.HARDEST}


@dataclass
class LightCurve:
    """A photometric time series on a single time axis, in days.

    ``time`` is in days in the time system described by ``time_format`` (e.g. ``btjd``). If the
    absolute reference is known, ``time_offset_jd`` is added to ``time`` to obtain JD/BJD.
    ``flux`` and ``flux_err`` are *relative* (median ~ 1) after loading.
    """

    time: np.ndarray
    flux: np.ndarray
    flux_err: np.ndarray
    quality: np.ndarray | None = None
    time_format: str = "relative"
    time_offset_jd: float | None = None
    mission: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.time = np.asarray(self.time, dtype=float)
        self.flux = np.asarray(self.flux, dtype=float)
        self.flux_err = np.asarray(self.flux_err, dtype=float)
        n = len(self.time)
        if not (len(self.flux) == n and len(self.flux_err) == n):
            raise ValueError("time, flux and flux_err must have equal length")
        if self.quality is not None:
            self.quality = np.asarray(self.quality).astype(np.int64)
            if len(self.quality) != n:
                raise ValueError("quality must have the same length as time")

    def __len__(self) -> int:
        return len(self.time)

    def select(self, mask: np.ndarray) -> "LightCurve":
        return LightCurve(
            time=self.time[mask], flux=self.flux[mask], flux_err=self.flux_err[mask],
            quality=None if self.quality is None else self.quality[mask],
            time_format=self.time_format, time_offset_jd=self.time_offset_jd,
            mission=self.mission, meta=dict(self.meta),
        )

    def sorted(self) -> "LightCurve":
        idx = np.argsort(self.time, kind="stable")
        return self.select(idx)

    @property
    def baseline(self) -> float:
        return float(self.time.max() - self.time.min()) if len(self) else 0.0

    def median_cadence_days(self) -> float:
        if len(self) < 2:
            return float("nan")
        return float(np.median(np.diff(np.sort(self.time))))
