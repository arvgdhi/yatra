"""Registry of analysis modules.

Each module declares what data it accepts, what it needs, its parameters, outputs, limitations and
the tests that validate it. Method selection is rule-based on the validated dataset profile:
an LLM is never in the loop for deciding which scientific method runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .transit.pipeline import DEFAULT_PARAMS, run_transit_pipeline


@dataclass
class ParamSpec:
    name: str
    type: str
    default: Any
    description: str
    advanced: bool = False
    min: float | None = None
    max: float | None = None
    choices: list[str] | None = None


@dataclass
class AnalysisModule:
    id: str
    name: str
    status: str                       # available | planned
    category: str                     # dataset category it consumes
    description: str
    assumptions: list[str]
    required_roles: list[str]
    prerequisites: list[str]
    parameters: list[ParamSpec] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    validation_tests: list[str] = field(default_factory=list)
    run: Callable[..., dict[str, Any]] | None = None

    def describe(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "run"}
        d["parameters"] = [p.__dict__ for p in self.parameters]
        return d


TRANSIT = AnalysisModule(
    id="transit_bls",
    name="Transit search (BLS) with model fit",
    status="available",
    category="photometric_time_series",
    description=("Cleans and detrends a light curve, searches for periodic box-shaped dips with Box Least Squares, "
                 "extracts multiple signals iteratively, screens each for common false-positive signatures, and fits "
                 "a limb-darkened transit model with uncertainties."),
    assumptions=["Transits are periodic, roughly box/limb-darkened shaped and shallower than ~15%",
                 "Noise is approximately white after detrending",
                 "Single-star photometry with no blend correction",
                 "Circular orbits and fixed quadratic limb darkening in the model fit"],
    required_roles=["time", "flux"],
    prerequisites=["≥200 valid points", "baseline ≥ 1 day", "median cadence ≤ 6 h"],
    parameters=[
        ParamSpec("quality_mask", "choice", DEFAULT_PARAMS["quality_mask"], "Quality-flag bitmask applied to cadences",
                  choices=["none", "default", "hard", "hardest"]),
        ParamSpec("sde_threshold", "float", 8.5, "Minimum signal detection efficiency to count a peak as a signal (default chosen from measured noise-only false alarms; see docs)", min=3, max=20),
        ParamSpec("min_depth_snr", "float", 7.1, "Minimum box-depth signal-to-noise (the usual Kepler detection threshold); a peak needs both this and the SDE threshold", min=3, max=20),
        ParamSpec("max_candidates", "int", 3, "Maximum number of signals to extract iteratively", min=1, max=6),
        ParamSpec("min_period", "float", None, "Minimum period to search (days); default 0.5", advanced=True, min=0.1),
        ParamSpec("max_period", "float", None, "Maximum period (days); default baseline/2", advanced=True),
        ParamSpec("max_duration", "float", 0.5, "Maximum transit duration to search (days)", advanced=True, min=0.05, max=2.0),
        ParamSpec("detrend", "bool", True, "Remove slow variability with a running median", advanced=True),
        ParamSpec("window_days", "float", None, "Detrending window (days); default max(0.75, 3×max duration)", advanced=True),
        ParamSpec("min_transits", "int", 2, "Minimum transits required within the baseline", advanced=True, min=2, max=5),
        ParamSpec("fit", "bool", True, "Fit a batman transit model to each signal", advanced=True),
        ParamSpec("mcmc", "bool", False, "Run emcee for posterior uncertainties (slower)", advanced=True),
        ParamSpec("star.teff", "float", None, "Stellar effective temperature (K), used for limb darkening", advanced=True),
        ParamSpec("star.radius_rsun", "float", None, "Stellar radius (R☉); required to report a planet radius", advanced=True),
        ParamSpec("star.radius_err_rsun", "float", None, "Uncertainty on stellar radius (R☉)", advanced=True),
    ],
    outputs=["candidate table", "BLS periodograms", "folded light curves with model overlay",
             "vetting checks", "fit parameters with uncertainties", "JSON/CSV/report export"],
    limitations=["Not validated as planets: results are candidate signals only",
                 "Single transits and long-period planets (<2 transits) are not found",
                 "Running-median detrending can partially suppress long-duration transits",
                 "Uncertainties assume white noise and fixed limb darkening and are likely underestimated",
                 "No centroid or difference-image analysis, so background eclipsing binaries cannot be excluded"],
    validation_tests=["tests/test_transit_recovery.py", "tests/test_transit_vetting.py"],
    run=run_transit_pipeline,
)

PLANNED = [
    AnalysisModule("rv_periodogram", "RV periodogram + Keplerian fit", "planned", "radial_velocity",
                   "Lomb–Scargle search and Keplerian orbit fit (not implemented).", [], ["time", "rv"], []),
    AnalysisModule("transmission_spectroscopy", "Atmospheric characterisation", "planned", "spectroscopy",
                   "Transmission/emission spectroscopy retrieval (not implemented).", [], ["wavelength", "flux"], []),
    AnalysisModule("direct_imaging", "Direct-imaging PSF subtraction", "planned", "image",
                   "ADI/RDI PSF subtraction (not implemented).", [], [], []),
    AnalysisModule("astrometric_orbit", "Astrometric orbit fit", "planned", "astrometry",
                   "Orbit fit to astrometric time series (not implemented).", [], ["time", "ra", "dec"], []),
]

REGISTRY: dict[str, AnalysisModule] = {m.id: m for m in [TRANSIT, *PLANNED]}


def get_module(module_id: str) -> AnalysisModule:
    if module_id not in REGISTRY:
        raise KeyError(f"Unknown analysis module '{module_id}'")
    return REGISTRY[module_id]


def applicable_modules(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Rule-based selection from the dataset profile (category + prerequisite checks)."""
    out = []
    for m in REGISTRY.values():
        if m.category != profile["category"]:
            continue
        info = next((x for x in profile["applicable_methods"] if x["id"] == m.id), {})
        out.append({"module": m.describe(), "status": info.get("status", m.status), "reason": info.get("reason")})
    return out
