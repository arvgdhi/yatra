"""Exo.MAST client (additional identifier resolution).

Documented endpoints (https://exo.mast.stsci.edu/docs/exoplanets_ws.html):
  GET /exoplanets/identifiers/?name=<name>   canonical planet name, other identifiers, star name, Kepler ID/TCE
  GET /exoplanets/autocomplete/?term=<term>  matching planet names
The documentation does not give response schemas, so parsing here is deliberately defensive and
keeps the raw payload. Exo.MAST is used only to enrich identity/aliases, never as the sole source
of physical parameters. Not verified against the live service in the build sandbox.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import get_settings
from .base import ArchiveError, cached, http

SOURCE = "Exo.MAST"


def _get(path: str, params: dict[str, Any]) -> Any:
    s = get_settings()
    try:
        with http() as c:
            r = c.get(f"{s.exomast_url}{path}", params=params, headers={"Accept": "application/json"})
    except ArchiveError:
        raise
    except httpx.TimeoutException as e:
        raise ArchiveError(SOURCE, "request timed out", retriable=True) from e
    except httpx.HTTPError as e:
        raise ArchiveError(SOURCE, f"network error: {e}", retriable=True) from e
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise ArchiveError(SOURCE, f"HTTP {r.status_code}", retriable=r.status_code >= 500, status=r.status_code)
    try:
        return r.json()
    except ValueError as e:
        raise ArchiveError(SOURCE, "response was not valid JSON") from e


def identifiers(name: str) -> dict[str, Any] | None:
    res = cached("exomast_identifiers", {"name": name.strip().lower()}, lambda: _get("/exoplanets/identifiers/", {"name": name}))
    data = res["data"]
    if not isinstance(data, dict):
        return None
    flat = {str(k): v for k, v in data.items()}
    aliases: list[str] = []
    for k, v in flat.items():
        if isinstance(v, str):
            aliases.append(v)
        elif isinstance(v, list):
            aliases.extend(str(x) for x in v if isinstance(x, (str, int)))
    return {"raw": flat, "aliases": sorted({a for a in aliases if a}), "provenance": res["provenance"]}


def autocomplete(term: str) -> list[str]:
    res = cached("exomast_autocomplete", {"term": term.strip().lower()}, lambda: _get("/exoplanets/autocomplete/", {"term": term}))
    data = res["data"]
    names: list[str] = []
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                names.extend(str(x) for x in v)
            elif isinstance(v, str):
                names.append(v)
    elif isinstance(data, list):
        names = [str(x) for x in data]
    return names[:15]
