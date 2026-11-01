"""Shared plumbing for archive clients: HTTP client, caching, provenance, errors.

Clients never fabricate results. When an archive is unreachable the caller receives an
``ArchiveError`` carrying the source and a human-readable reason, and the UI reports it.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

import httpx

from .. import db
from ..config import get_settings


class ArchiveError(Exception):
    def __init__(self, source: str, message: str, *, retriable: bool = False, status: int | None = None):
        super().__init__(f"{source}: {message}")
        self.source, self.message, self.retriable, self.status = source, message, retriable, status

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "message": self.message, "retriable": self.retriable, "status": self.status}


def user_agent() -> str:
    s = get_settings()
    base = "ExoplanetExplorer/0.1 (+research tool)"
    return f"{base} contact:{s.contact_email}" if s.contact_email else base


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    s = get_settings()
    return httpx.Client(timeout=s.http_timeout_s, headers={"User-Agent": user_agent()}, transport=transport,
                        follow_redirects=True)


# A transport can be injected (tests use httpx.MockTransport) without touching the network.
_TRANSPORT: httpx.BaseTransport | None = None


def set_transport(t: httpx.BaseTransport | None) -> None:
    global _TRANSPORT
    _TRANSPORT = t


def http() -> httpx.Client:
    if get_settings().offline:
        raise ArchiveError("network", "The server is running in offline mode (EXPLORER_OFFLINE=true); archive access is disabled.")
    return make_client(_TRANSPORT)


def cache_key(source: str, query: Any) -> str:
    return source + ":" + hashlib.sha256(json.dumps(query, sort_keys=True, default=str).encode()).hexdigest()[:32]


def cached(source: str, query: Any, fetch: Callable[[], Any], *, refresh: bool = False) -> dict[str, Any]:
    """Return {data, provenance}; provenance records the source, query, retrieval time and cache status."""
    key = cache_key(source, query)
    if not refresh:
        hit = db.cache_get(key)
        if hit is not None:
            data, ts = hit
            return {"data": data, "provenance": {"source": source, "query": query, "retrieved_at": ts, "from_cache": True}}
    data = fetch()
    ts = db.cache_put(key, data, source)
    return {"data": data, "provenance": {"source": source, "query": query, "retrieved_at": ts, "from_cache": False}}


def adql_literal(value: str) -> str:
    """Quote a user string for an ADQL literal. Restrict characters rather than trusting escaping."""
    cleaned = re.sub(r"[^A-Za-z0-9 .+\-_'*:]", "", value)[:80].strip()
    return "'" + cleaned.replace("'", "''") + "'"


def f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None
