"""Target search and detail assembly across NASA Exoplanet Archive, MAST and Exo.MAST.

Each source is queried independently; a failure in one becomes an entry in ``errors`` and the
other sources still render (partial results). Records carry the archive they came from and when
they were retrieved. A catalogue entry never implies that observations exist.
"""
from __future__ import annotations

import re
from typing import Any

from .. import db
from ..archives import exomast, mast, nasa
from ..archives.base import ArchiveError
from ..models import planet_estimator


def search(q: str) -> dict[str, Any]:
    q = (q or "").strip()
    if len(q) < 2:
        return {"results": [], "errors": [], "provenance": []}
    errors: list[dict] = []
    prov: list[dict] = []
    results: list[dict[str, Any]] = []
    try:
        r = nasa.search(q)
        prov.append(r["provenance"])
        for e in r["results"]:
            e = dict(e)
            e["key"] = ("tic:" + str(re.sub(r"\D", "", e["tic_id"])) if e["kind"] == "tic_candidate_host"
                        else "kic:" + str(e["kic"]) if e["kind"] == "kic_candidate_host"
                        else "host:" + e["host"])
            e["source"] = "NASA Exoplanet Archive"
            results.append(e)
    except ArchiveError as ex:
        errors.append(ex.to_dict())
    if not results:
        # Not in the exoplanet catalogues: resolve the name to a position so MAST observations can still be found.
        try:
            hit = mast.name_lookup(q)
            if hit:
                prov.append(hit["provenance"])
                results.append({"kind": "resolved_object", "host": hit["canonical_name"] or q, "planets": [],
                                "key": f"pos:{hit['ra_deg']:.6f},{hit['dec_deg']:.6f}:{hit['canonical_name'] or q}",
                                "object_type": hit.get("object_type"), "source": "MAST name resolver",
                                "note": "Not found in the exoplanet catalogues; resolved to a sky position only."})
        except ArchiveError as ex:
            errors.append(ex.to_dict())
    return {"results": results, "errors": errors, "provenance": prov}


def detail(key: str) -> dict[str, Any]:
    kind, _, rest = key.partition(":")
    errors: list[dict] = []
    prov: list[dict] = []
    star: dict[str, Any] | None = None
    planets: list[dict] = []
    candidates: list[dict] = []
    aliases: list[str] = []
    label = rest
    ra = dec = None
    tic = kic = None

    if kind == "host":
        label = rest
        try:
            sysd = nasa.host_system(rest)
            prov.append(sysd["provenance"])
            star, planets = sysd["star"], sysd["planets"]
            if star:
                ra, dec = star["ra_deg"], star["dec_deg"]
                t = (star["ids"].get("tic_id") or "")
                if m := re.search(r"\d+", t):
                    tic = int(m.group())
        except ArchiveError as ex:
            errors.append(ex.to_dict())
        if planets:
            try:
                ids = exomast.identifiers(planets[0]["name"])
                if ids:
                    aliases = ids["aliases"]
                    prov.append(ids["provenance"])
            except ArchiveError as ex:
                errors.append(ex.to_dict())
    elif kind == "tic":
        tic = int(rest)
        label = f"TIC {tic}"
    elif kind == "kic":
        kic = int(rest)
        label = f"KIC {kic}"
    elif kind == "pos":
        coords, _, label = rest.partition(":")
        ra_s, dec_s = coords.split(",")
        ra, dec = float(ra_s), float(dec_s)
    else:
        raise ValueError("Unknown target key")

    if tic is not None:
        try:
            t = nasa.toi_for_tic(tic)
            prov.append(t["provenance"])
            candidates += t["candidates"]
            if t["candidates"] and ra is None:
                ra, dec = t["candidates"][0]["ra_deg"], t["candidates"][0]["dec_deg"]
        except ArchiveError as ex:
            errors.append(ex.to_dict())
    if kic is not None:
        try:
            k = nasa.koi_for_kic(kic)
            prov.append(k["provenance"])
            candidates += k["candidates"]
        except ArchiveError as ex:
            errors.append(ex.to_dict())
        if ra is None:
            try:
                hit = mast.name_lookup(f"KIC {kic}")
                if hit:
                    ra, dec = hit["ra_deg"], hit["dec_deg"]
                    prov.append(hit["provenance"])
            except ArchiveError as ex:
                errors.append(ex.to_dict())

    observations: list[dict] = []
    if ra is not None and dec is not None:
        try:
            o = mast.find_observations(ra, dec)
            prov.append(o["provenance"])
            observations = o["observations"]
        except ArchiveError as ex:
            errors.append(ex.to_dict())
    else:
        errors.append({"source": "target", "message": "No sky position is available for this target, so observations could not be searched."})

    planets, estimate_model = planet_estimator.enrich(planets, star)
    _remember(key, label, kind)
    groups: dict[str, list[dict]] = {}
    for ob in observations:
        groups.setdefault(f"{ob['mission']} / {ob['pipeline'] or 'unknown pipeline'}", []).append(ob)
    for g in groups.values():
        g.sort(key=lambda x: (x.get("start_mjd") or 0))
    return {
        "key": key, "label": label, "star": star, "position": {"ra_deg": ra, "dec_deg": dec},
        "aliases": aliases,
        "published_planets": planets,        # archive values remain confirmed; calculated fields are explicitly tagged
        "catalog_candidates": candidates,    # TOI / KOI entries, not confirmed planets unless the archive says so
        "observations": groups, "n_observations": len(observations),
        "errors": errors, "provenance": prov,
        "estimate_model": estimate_model,
        "notes": ["Catalogue membership does not imply that observations exist; observations come from MAST.",
                  "Values labelled ML estimate are locally calculated approximations, not archive measurements or confirmation."],
    }


def known_planets_for_analysis(det: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for p in det.get("published_planets", []):
        if p.get("period"):
            out.append({"name": p["name"], "period": p["period"]["value"], "status": "published"})
    for c in det.get("catalog_candidates", []):
        if c.get("period"):
            out.append({"name": c["name"], "period": c["period"], "status": c.get("status", "candidate"),
                        "disposition": c.get("disposition")})
    return out


def _remember(key: str, label: str, kind: str) -> None:
    with db.connect() as c:
        c.execute("INSERT OR REPLACE INTO recent_targets(target_key, label, kind, visited_at) VALUES (?,?,?,?)",
                  (key, label, kind, db.now()))


def recent(limit: int = 8) -> list[dict[str, Any]]:
    with db.connect() as c:
        rows = c.execute("SELECT target_key, label, kind, visited_at FROM recent_targets ORDER BY visited_at DESC LIMIT ?",
                         (limit,)).fetchall()
    return [dict(r) for r in rows]
