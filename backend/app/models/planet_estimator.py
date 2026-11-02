"""Inference for absent catalogue properties using a checked-in local model.

The model is deliberately simple and inspectable: ridge regressions trained from
NASA Exoplanet Archive composite parameters. It never overwrites archive data and
never classifies an object as a confirmed planet.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "planet_property_model.json"
_UNITS = {"radius": "R_earth", "mass": "M_earth", "transit_duration": "h", "transit_depth": "%"}


def _num(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("value")
    try:
        n = float(value)
        return n if math.isfinite(n) and n > 0 else None
    except (TypeError, ValueError):
        return None


@lru_cache
def _model() -> dict[str, Any] | None:
    try:
        with MODEL_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if data.get("schema_version") == 1 else None
    except (OSError, json.JSONDecodeError):
        return None


def _features(planet: dict[str, Any], star: dict[str, Any] | None) -> dict[str, float | None]:
    star = star or {}
    return {
        "period_days": _num(planet.get("period")),
        "radius_earth": _num(planet.get("radius")),
        "mass_earth": _num(planet.get("mass")),
        "duration_hours": _num(planet.get("transit_duration")),
        "depth_percent": _num(planet.get("transit_depth")),
        "semi_major_axis_au": _num(planet.get("semi_major_axis")),
        "star_radius_solar": _num(star.get("radius")),
        "star_mass_solar": _num(star.get("mass")),
        "star_teff_k": _num(star.get("teff")),
    }


def _error(fitted: dict[str, Any]) -> tuple[float | None, str | None]:
    """Typical log10 error of the model. Held-out error is preferred; the in-sample error is optimistic and is labelled as such."""
    for key, basis in (("holdout_rmse_log10", "held-out data"), ("rmse_log10", "in-sample fit only, so optimistic; retrain to get a held-out error")):
        v = fitted.get(key)
        if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0:
            return float(v), basis
    return None, None


def enrich(planets: list[dict[str, Any]], star: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Fill supported missing numerical values, always with local-model provenance."""
    model = _model()
    if not model:
        return planets, None
    enriched: list[dict[str, Any]] = []
    made = 0
    for original in planets:
        planet = dict(original)
        available = _features(planet, star)
        for field, fitted in model.get("models", {}).items():
            output = {"radius": "radius", "mass": "mass", "transit_duration": "transit_duration", "transit_depth": "transit_depth"}.get(field)
            if not output or planet.get(output) is not None:
                continue
            names = fitted.get("features", [])
            # Do not fabricate a result from nothing; at least two observed properties are required.
            present = sum(available.get(name) is not None for name in names)
            if present < 2:
                continue
            try:
                transformed = [math.log10(available[name]) if available.get(name) else fitted["medians"][i]
                               for i, name in enumerate(names)]
                normalized = [(x - fitted["means"][i]) / fitted["scales"][i] for i, x in enumerate(transformed)]
                log_estimate = float(fitted["intercept"]) + sum(float(w) * x for w, x in zip(fitted["weights"], normalized))
                value = 10 ** log_estimate
            except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
                continue
            if not math.isfinite(value) or value <= 0:
                continue
            err, basis = _error(fitted)
            factor = 10 ** err if err is not None else None
            note = "Approximate ML estimate; not a measurement or confirmation."
            if factor is not None:
                note += (f" Typical error about a factor of {factor:.2f} up or down (1 sigma, {basis}).")
            planet[output] = {
                "value": value, "unit": _UNITS[field], "calculated": True,
                "estimate": {
                    "method": "Local ridge regression", "model_version": model.get("version"),
                    "training_rows": fitted.get("sample_count"), "features_used": present,
                    "error_log10": err, "error_factor": factor, "error_basis": basis,
                    "uncertainty_note": note,
                },
            }
            available = _features(planet, star)
            made += 1
        enriched.append(planet)
    meta = None
    if made:
        meta = {"version": model.get("version"), "trained_at": model.get("trained_at"), "source": model.get("source"), "estimates": made}
    return enriched, meta
