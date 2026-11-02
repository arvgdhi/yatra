"""Train the portable exoplanet-property model on this machine.

Run from backend: ``python ../scripts/train_planet_property_model.py``.
It queries the public NASA Exoplanet Archive once and writes a compact JSON model
to ``backend/models/``. Commit that JSON so deployments only infer; they do not
retrain or contact the archive.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "models" / "planet_property_model.json"
URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
FEATURES = ["period_days", "radius_earth", "mass_earth", "duration_hours", "depth_percent", "semi_major_axis_au", "star_radius_solar", "star_mass_solar", "star_teff_k"]
TARGETS = {"radius": "radius_earth", "mass": "mass_earth", "transit_duration": "duration_hours", "transit_depth": "depth_percent"}
COLUMNS = {"period_days": "pl_orbper", "radius_earth": "pl_rade", "mass_earth": "pl_bmasse", "duration_hours": "pl_trandur", "depth_percent": "pl_trandep", "semi_major_axis_au": "pl_orbsmax", "star_radius_solar": "st_rad", "star_mass_solar": "st_mass", "star_teff_k": "st_teff"}


def rows() -> list[dict]:
    query = "select top 50000 " + ", ".join(COLUMNS.values()) + " from pscomppars"
    with urlopen(URL + "?" + urlencode({"query": query, "format": "json"}), timeout=90) as response:
        return json.load(response)


def train(data: list[dict]) -> dict:
    matrix = np.array([[r.get(COLUMNS[f]) for f in FEATURES] for r in data], dtype=float)
    result: dict[str, dict] = {}
    for key, target in TARGETS.items():
        target_ix = FEATURES.index(target)
        mask = np.isfinite(matrix[:, target_ix]) & (matrix[:, target_ix] > 0)
        subset = matrix[mask]
        y = np.log10(subset[:, target_ix])
        input_ix = [i for i, f in enumerate(FEATURES) if f != target]
        names = [FEATURES[i] for i in input_ix]
        x = subset[:, input_ix]
        valid = np.isfinite(x) & (x > 0)
        transformed = np.where(valid, np.log10(np.where(valid, x, 1)), np.nan)
        medians = np.nanmedian(transformed, axis=0)
        transformed = np.where(np.isfinite(transformed), transformed, medians)
        means = transformed.mean(axis=0)
        scales = transformed.std(axis=0)
        scales[scales < 1e-7] = 1
        z = (transformed - means) / scales
        # Mild ridge penalty keeps coefficients stable and makes the stored model portable.
        ridge = 0.25

        def solve(zz, yy):
            return np.linalg.solve(zz.T @ zz + ridge * np.eye(zz.shape[1]), zz.T @ (yy - yy.mean()))

        # Honest error: fit on 80 % of rows, score on the unseen 20 % (fixed seed). The stored model is then refit on all rows.
        perm = np.random.default_rng(20261102).permutation(len(y))
        cut = int(0.8 * len(y))
        tr, te = perm[:cut], perm[cut:]
        w_tr = solve(z[tr], y[tr])
        pred_te = y[tr].mean() + z[te] @ w_tr
        holdout_rmse = float(np.sqrt(np.mean((pred_te - y[te]) ** 2)))
        holdout_r2 = float(1 - np.sum((pred_te - y[te]) ** 2) / np.sum((y[te] - y[te].mean()) ** 2))
        weights = solve(z, y)
        prediction = y.mean() + z @ weights
        result[key] = {"holdout_rmse_log10": holdout_rmse, "holdout_r2": holdout_r2, "holdout_n": int(len(te)),"features": names, "medians": medians.tolist(), "means": means.tolist(), "scales": scales.tolist(), "weights": weights.tolist(), "intercept": float(y.mean()), "sample_count": int(len(y)), "rmse_log10": float(np.sqrt(np.mean((prediction - y) ** 2)))}
    return {"schema_version": 1, "version": "local-ridge-2", "trained_at": datetime.now(timezone.utc).isoformat(), "source": "NASA Exoplanet Archive pscomppars (local training run)", "models": result}


if __name__ == "__main__":
    try:
        model = train(rows())
    except Exception as exc:
        print(f"Training failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")
    summary = ", ".join(f"{key}: {fitted['sample_count']} rows" for key, fitted in model["models"].items())
    print(f"Wrote {OUT} ({summary})")
    for key, fitted in model["models"].items():
        print(f"  {key}: held-out RMSE {fitted['holdout_rmse_log10']:.3f} dex (x{10 ** fitted['holdout_rmse_log10']:.2f}), R^2 {fitted['holdout_r2']:.2f}, n={fitted['holdout_n']}")
