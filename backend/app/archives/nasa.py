"""NASA Exoplanet Archive client (TAP, synchronous endpoint).

Verified against the archive's TAP documentation:
  endpoint  https://exoplanetarchive.ipac.caltech.edu/TAP/sync  (params: query, format=json)
  tables    pscomppars (composite confirmed planets), toi (TESS Objects of Interest),
            cumulative (Kepler KOI cumulative)
  columns   names used below are taken from the archive's column definition pages
            (API_PS_columns, API_TOI_columns, API_kepcandidate_columns).
Queries use ``select *`` wherever a column list is not verified, and read only verified names.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

from ..config import get_settings
from .base import ArchiveError, adql_literal, cached, f, http

SOURCE_PS = "NASA Exoplanet Archive: pscomppars"
SOURCE_TOI = "NASA Exoplanet Archive: toi"
SOURCE_KOI = "NASA Exoplanet Archive: cumulative"


def tap_query(adql: str, source: str = "NASA Exoplanet Archive") -> list[dict[str, Any]]:
    s = get_settings()
    try:
        with http() as c:
            r = c.get(s.nasa_tap_url, params={"query": adql, "format": "json"})
    except ArchiveError:
        raise
    except httpx.TimeoutException as e:
        raise ArchiveError(source, "request timed out", retriable=True) from e
    except httpx.HTTPError as e:
        raise ArchiveError(source, f"network error: {e}", retriable=True) from e
    if r.status_code != 200:
        raise ArchiveError(source, f"HTTP {r.status_code}: {r.text[:200].strip()}", retriable=r.status_code >= 500,
                           status=r.status_code)
    try:
        rows = r.json()
    except ValueError as e:
        raise ArchiveError(source, "response was not valid JSON (unexpected format)") from e
    if not isinstance(rows, list):
        raise ArchiveError(source, "unexpected response shape (expected a list of rows)")
    return rows


# ------------------------------------------------------------------------------------------
# Query-string interpretation
# ------------------------------------------------------------------------------------------
def parse_identifier(q: str) -> dict[str, Any]:
    """Recognise catalogue-style identifiers; otherwise treat as a free-text name."""
    s = q.strip()
    if m := re.fullmatch(r"(?i)tic[\s_-]*(\d{1,12})", s):
        return {"type": "tic", "id": int(m.group(1))}
    if m := re.fullmatch(r"(?i)toi[\s_-]*(\d{1,6})(?:\.\d+)?", s):
        return {"type": "toi", "id": int(m.group(1))}
    if m := re.fullmatch(r"(?i)kic[\s_-]*(\d{1,10})", s):
        return {"type": "kic", "id": int(m.group(1))}
    if m := re.fullmatch(r"(?i)k(?:oi)?[\s_-]*0*(\d{1,6})(?:\.\d+)?", s) and re.match(r"(?i)koi", s):
        return {"type": "koi", "id": int(re.search(r"\d+", s).group())}
    return {"type": "name", "text": s}


# ------------------------------------------------------------------------------------------
# Searching
# ------------------------------------------------------------------------------------------
def search(q: str, limit: int = 12) -> dict[str, Any]:
    """Find hosts/planets matching the query in the confirmed-planet composite table.

    Returns {results: [{host, planets:[names], ...}], provenance}. TIC/KIC/TOI/KOI identifiers
    are resolved through their own tables so candidates without a confirmed planet are found too.
    """
    ident = parse_identifier(q)

    def fetch() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if ident["type"] == "name":
            # The archive uses the IAU constellation abbreviation ("pi Men"), while
            # astronomers often search the fully written form ("Pi Mensae").
            # Keep the user's text as the display query but broaden this known alias.
            archive_text = {"pi mensae": "pi men"}.get(ident["text"].lower(), ident["text"].lower())
            lit = adql_literal(archive_text)
            starts = lit[:-1] + "%'"
            contains = lit[:-1] + "%'" if len(archive_text) < 3 else "'%" + lit[1:-1] + "%'"
            adql = (f"select top {int(limit) * 4} pl_name, hostname, sy_pnum, discoverymethod, tic_id "
                    f"from pscomppars where lower(pl_name) like {starts} or lower(hostname) like {starts} "
                    f"or lower(pl_name) like {contains} or lower(hostname) like {contains} order by hostname, pl_name")
            rows = tap_query(adql, SOURCE_PS)
            hosts: dict[str, dict[str, Any]] = {}
            for r in rows:
                h = r.get("hostname")
                if not h:
                    continue
                e = hosts.setdefault(h, {"kind": "host", "host": h, "planets": [], "tic_id": r.get("tic_id"),
                                         "n_planets": r.get("sy_pnum")})
                if r.get("pl_name"):
                    e["planets"].append(r["pl_name"])
            out = list(hosts.values())[:limit]
        elif ident["type"] == "tic":
            rows = tap_query(f"select top 5 pl_name, hostname, tic_id from pscomppars where tic_id = {adql_literal('TIC ' + str(ident['id']))}", SOURCE_PS)
            for r in rows:
                out.append({"kind": "host", "host": r["hostname"], "planets": [r["pl_name"]], "tic_id": r.get("tic_id")})
            if not out:
                t = tap_query(f"select top 5 tid, toi, tfopwg_disp from toi where tid = {int(ident['id'])}", SOURCE_TOI)
                if t:
                    out.append({"kind": "tic_candidate_host", "host": f"TIC {ident['id']}", "planets": [],
                                "tic_id": f"TIC {ident['id']}", "candidates": [x.get("toi") for x in t]})
        elif ident["type"] == "toi":
            t = tap_query(f"select top 20 tid, toi, tfopwg_disp from toi where toipfx = {int(ident['id'])}", SOURCE_TOI)
            if t:
                out.append({"kind": "tic_candidate_host", "host": f"TIC {int(t[0]['tid'])}", "planets": [],
                            "tic_id": f"TIC {int(t[0]['tid'])}", "candidates": [x.get("toi") for x in t],
                            "label": f"TOI-{ident['id']}"})
        elif ident["type"] == "kic":
            k = tap_query(f"select top 20 kepoi_name, kepler_name, koi_disposition from cumulative where kepid = {int(ident['id'])}", SOURCE_KOI)
            if k:
                out.append({"kind": "kic_candidate_host", "host": f"KIC {ident['id']}", "planets": [],
                            "candidates": [x.get("kepoi_name") for x in k], "kic": ident["id"]})
        elif ident["type"] == "koi":
            lit = adql_literal("K%05d." % ident["id"])
            k = tap_query(f"select top 20 kepid, kepoi_name, kepler_name, koi_disposition from cumulative where kepoi_name like {lit[:-1]}%'", SOURCE_KOI)
            if k:
                out.append({"kind": "kic_candidate_host", "host": f"KIC {int(k[0]['kepid'])}", "planets": [],
                            "candidates": [x.get("kepoi_name") for x in k], "kic": int(k[0]["kepid"])})
        return out

    res = cached("nasa_search", {"q": q.strip().lower(), "limit": limit, "query_version": 2}, fetch)
    return {"results": res["data"], "provenance": res["provenance"], "identifier": ident}


# ------------------------------------------------------------------------------------------
# Target detail
# ------------------------------------------------------------------------------------------
def _planet(row: dict[str, Any]) -> dict[str, Any]:
    def val(col: str, unit: str | None = None, err: bool = True) -> dict[str, Any] | None:
        v = f(row.get(col))
        if v is None:
            return None
        d: dict[str, Any] = {"value": v, "unit": unit}
        if err:
            e1, e2 = f(row.get(col + "err1")), f(row.get(col + "err2"))
            if e1 is not None or e2 is not None:
                d["err_plus"], d["err_minus"] = e1, e2
        return d

    return {
        "name": row.get("pl_name"), "status": "confirmed",
        "discovery": {"method": row.get("discoverymethod"), "year": row.get("disc_year"),
                      "facility": row.get("disc_facility")},
        "period": val("pl_orbper", "d"), "radius": val("pl_rade", "R_earth"),
        "mass": val("pl_bmasse", "M_earth"), "transit_duration": val("pl_trandur", "h"),
        "transit_depth": val("pl_trandep", "%"), "transit_midpoint": val("pl_tranmid", "BJD"),
        "semi_major_axis": val("pl_orbsmax", "AU", err=False),
        "reference": row.get("pl_refname"),
    }


def _star(row: dict[str, Any]) -> dict[str, Any]:
    def val(col: str, unit: str) -> dict[str, Any] | None:
        v = f(row.get(col))
        if v is None:
            return None
        d = {"value": v, "unit": unit}
        e1, e2 = f(row.get(col + "err1")), f(row.get(col + "err2"))
        if e1 is not None or e2 is not None:
            d["err_plus"], d["err_minus"] = e1, e2
        return d

    return {
        "name": row.get("hostname"), "ra_deg": f(row.get("ra")), "dec_deg": f(row.get("dec")),
        "teff": val("st_teff", "K"), "radius": val("st_rad", "R_sun"), "mass": val("st_mass", "M_sun"),
        "logg": val("st_logg", "log10(cm/s^2)"), "distance": val("sy_dist", "pc"),
        "ids": {k: row.get(k) for k in ("tic_id", "hd_name", "hip_name", "gaia_dr2_id", "gaia_dr3_id") if row.get(k)},
        "n_stars": row.get("sy_snum"), "n_planets": row.get("sy_pnum"),
        "reference": row.get("st_refname"),
    }


def host_system(host: str) -> dict[str, Any]:
    """Confirmed planets and host-star parameters for one host star (composite table)."""
    lit = adql_literal(host)

    def fetch():
        return tap_query(f"select * from pscomppars where hostname = {lit}", SOURCE_PS)

    res = cached("nasa_host", {"host": host}, fetch)
    rows = res["data"]
    if not rows:
        return {"star": None, "planets": [], "provenance": res["provenance"]}
    return {"star": _star(rows[0]), "planets": [_planet(r) for r in rows], "provenance": res["provenance"]}


def toi_for_tic(tic: int) -> dict[str, Any]:
    def fetch():
        return tap_query(f"select * from toi where tid = {int(tic)}", SOURCE_TOI)

    res = cached("nasa_toi", {"tic": int(tic)}, fetch)
    cands = []
    for r in res["data"]:
        cands.append({
            "name": f"TOI-{r.get('toi')}", "status": "candidate", "catalog": "TESS Objects of Interest",
            "disposition": r.get("tfopwg_disp"), "period": f(r.get("pl_orbper")),
            "transit_midpoint_bjd": f(r.get("pl_tranmid")), "duration_hours": f(r.get("pl_trandurh")),
            "depth_ppm": f(r.get("pl_trandep")), "radius_earth": f(r.get("pl_rade")),
            "ra_deg": f(r.get("ra")), "dec_deg": f(r.get("dec")), "teff": f(r.get("st_teff")),
            "star_radius_rsun": f(r.get("st_rad")), "tmag": f(r.get("st_tmag")),
        })
    return {"candidates": cands, "provenance": res["provenance"]}


def koi_for_kic(kic: int) -> dict[str, Any]:
    def fetch():
        return tap_query(f"select * from cumulative where kepid = {int(kic)}", SOURCE_KOI)

    res = cached("nasa_koi", {"kic": int(kic)}, fetch)
    cands = []
    for r in res["data"]:
        cands.append({
            "name": r.get("kepler_name") or r.get("kepoi_name"), "koi": r.get("kepoi_name"),
            "status": "confirmed" if r.get("koi_disposition") == "CONFIRMED" else
                      ("false_positive" if r.get("koi_disposition") == "FALSE POSITIVE" else "candidate"),
            "catalog": "Kepler KOI cumulative", "disposition": r.get("koi_disposition"),
            "period": f(r.get("koi_period")), "transit_midpoint_bkjd": f(r.get("koi_time0bk")),
            "duration_hours": f(r.get("koi_duration")), "depth_ppm": f(r.get("koi_depth")),
            "radius_earth": f(r.get("koi_prad")), "teff": f(r.get("koi_steff")),
            "star_radius_rsun": f(r.get("koi_srad")),
        })
    return {"candidates": cands, "provenance": res["provenance"]}
