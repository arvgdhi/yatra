"""Collect library versions recorded with every analysis for reproducibility."""
from __future__ import annotations

import platform
from importlib import metadata

_PACKAGES = ["numpy", "scipy", "pandas", "astropy", "batman-package", "emcee", "fastapi"]


def dependency_versions() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for name in _PACKAGES:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = "not installed"
    return out
