"""MAST client.

Verified against public documentation:
  * invoke endpoint   https://mast.stsci.edu/api/v0/invoke  (POST form field ``request`` = JSON with
                      service/params/format) - confirmed from the MAST API description and astrobase's client.
  * Mast.Name.Lookup  params {input, format:'json'}; response ``resolvedCoordinate[]`` with
                      canonicalName, ra, decl, objectType (astroquery documentation).
Observation search, product listing and file download go through ``astroquery.mast`` (the MAST
team's maintained client) rather than hand-built URLs, because the product/download endpoints
could not be confirmed from the documentation reachable at build time.

Supported analysis inputs are SPOC light-curve files for TESS and Kepler/K2 (``*_lc.fits`` for
TESS; ``*_llc.fits`` / ``*_slc.fits`` for Kepler long/short cadence).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

from .. import db
from ..config import get_settings
from .base import ArchiveError, cached, f, http

SOURCE = "MAST"
MJD_TO_ISO = None  # computed lazily with astropy

LC_FILE_RE = re.compile(r"(_lc\.fits|_llc\.fits|_slc\.fits)$", re.I)
MISSIONS = ["TESS", "Kepler", "K2"]


def name_lookup(name: str) -> dict[str, Any] | None:
    """Resolve a name to coordinates using MAST's Mast.Name.Lookup service."""
    s = get_settings()
    req = {"service": "Mast.Name.Lookup", "params": {"input": name, "format": "json"}, "format": "json"}

    def fetch():
        try:
            with http() as c:
                r = c.post(s.mast_invoke_url, data={"request": json.dumps(req)})
        except ArchiveError:
            raise
        except httpx.TimeoutException as e:
            raise ArchiveError(SOURCE, "name lookup timed out", retriable=True) from e
        except httpx.HTTPError as e:
            raise ArchiveError(SOURCE, f"network error: {e}", retriable=True) from e
        if r.status_code != 200:
            raise ArchiveError(SOURCE, f"HTTP {r.status_code} from name lookup", retriable=r.status_code >= 500,
                               status=r.status_code)
        try:
            return r.json()
        except ValueError as e:
            raise ArchiveError(SOURCE, "name lookup returned non-JSON") from e

    res = cached("mast_name", {"name": name.strip().lower()}, fetch)
    data = res["data"]
    resolved = (data or {}).get("resolvedCoordinate") or []
    if not resolved:
        return None
    r0 = resolved[0]
    ra, dec = f(r0.get("ra")), f(r0.get("decl"))
    if ra is None or dec is None:
        return None
    return {"canonical_name": r0.get("canonicalName"), "ra_deg": ra, "dec_deg": dec,
            "object_type": r0.get("objectType"), "resolver": r0.get("resolver"),
            "provenance": res["provenance"]}


# ------------------------------------------------------------------------------------------
# astroquery-backed discovery. ``_obs()`` is a seam so tests can inject a fake.
# ------------------------------------------------------------------------------------------
def _obs():
    from astroquery.mast import Observations
    return Observations


def _mjd_iso(mjd: float | None) -> str | None:
    if mjd is None:
        return None
    from astropy.time import Time
    try:
        return Time(mjd, format="mjd").isot[:10]
    except Exception:
        return None


def _table_rows(tbl) -> list[dict[str, Any]]:
    rows = []
    for r in tbl:
        d: dict[str, Any] = {}
        for k in tbl.colnames:
            v = r[k]
            if hasattr(v, "mask") and getattr(v, "mask", False) is True:
                v = None
            if hasattr(v, "item"):
                try:
                    v = v.item()
                except Exception:
                    pass
            if isinstance(v, float) and v != v:
                v = None
            d[k] = v
        rows.append(d)
    return rows


def find_observations(ra_deg: float, dec_deg: float, radius_arcsec: float = 5.0) -> dict[str, Any]:
    """Time-series observations from TESS/Kepler/K2 near a position."""
    def fetch():
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        try:
            tbl = _obs().query_criteria(coordinates=SkyCoord(ra_deg, dec_deg, unit="deg"),
                                        radius=radius_arcsec * u.arcsec, obs_collection=MISSIONS,
                                        dataproduct_type="timeseries")
        except Exception as e:  # astroquery raises various network/remote errors
            raise ArchiveError(SOURCE, f"observation query failed: {e}", retriable=True) from e
        return _table_rows(tbl)

    res = cached("mast_obs", {"ra": round(ra_deg, 5), "dec": round(dec_deg, 5), "r": radius_arcsec}, fetch)
    return {"observations": [_obs_summary(r) for r in res["data"]], "provenance": res["provenance"]}


def _obs_summary(r: dict[str, Any]) -> dict[str, Any]:
    prov = (r.get("provenance_name") or "").upper()
    coll = r.get("obs_collection")
    supported = (coll == "TESS" and prov == "SPOC") or (coll in ("Kepler", "K2") and prov in ("KEPLER", "K2", ""))
    exp = f(r.get("t_exptime"))
    return {
        "obsid": str(r.get("obsid")), "obs_id": r.get("obs_id"), "mission": coll, "pipeline": r.get("provenance_name"),
        "target_name": r.get("target_name"), "sequence": r.get("sequence_number"),
        "instrument": r.get("instrument_name"), "exposure_s": exp,
        "start_mjd": f(r.get("t_min")), "end_mjd": f(r.get("t_max")),
        "start_date": _mjd_iso(f(r.get("t_min"))), "end_date": _mjd_iso(f(r.get("t_max"))),
        "analysis_supported": bool(supported),
        "unsupported_reason": None if supported else
        "Only SPOC TESS and Kepler/K2 light-curve products are currently supported for analysis.",
    }


def list_light_curve_products(obsid: str) -> dict[str, Any]:
    def fetch():
        try:
            tbl = _obs().get_product_list(str(obsid))
        except Exception as e:
            raise ArchiveError(SOURCE, f"product listing failed: {e}", retriable=True) from e
        return _table_rows(tbl)

    res = cached("mast_products", {"obsid": str(obsid)}, fetch)
    prods = []
    for r in res["data"]:
        fn = r.get("productFilename") or ""
        if not LC_FILE_RE.search(fn):
            continue
        prods.append({"filename": fn, "uri": r.get("dataURI"), "size_bytes": r.get("size"),
                      "description": r.get("description"), "group": r.get("productSubGroupDescription")})
    return {"products": prods, "provenance": res["provenance"]}


def download_product(uri: str, size_bytes: int | None, dest_dir: Path) -> Path:
    s = get_settings()
    if size_bytes and size_bytes > s.max_product_mb * 1024 * 1024:
        raise ArchiveError(SOURCE, f"product is {size_bytes / 1e6:.0f} MB, above the {s.max_product_mb} MB limit")
    if not re.fullmatch(r"mast:[A-Za-z0-9_./\-]+", uri or "") or ".." in (uri or "").split("/") or "//" in (uri or ""):
        raise ArchiveError(SOURCE, "refusing to download: unexpected product URI")
    dest_dir.mkdir(parents=True, exist_ok=True)
    local = dest_dir / re.sub(r"[^A-Za-z0-9_.\-]", "_", uri.split("/")[-1])
    if local.exists() and local.stat().st_size > 0:
        return local
    try:
        status, msg, _ = _obs().download_file(uri, local_path=str(local), cache=False)
    except Exception as e:
        local.unlink(missing_ok=True)
        raise ArchiveError(SOURCE, f"download failed: {e}", retriable=True) from e
    if str(status).upper() != "COMPLETE" or not local.exists():
        local.unlink(missing_ok=True)
        raise ArchiveError(SOURCE, f"download did not complete ({status}: {msg})", retriable=True)
    return local
