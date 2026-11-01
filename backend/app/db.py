"""SQLite persistence: datasets, analyses, archive cache and recent targets."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,              -- 'upload' | 'archive'
    original_name TEXT,
    stored_path TEXT,
    sha256 TEXT,
    size_bytes INTEGER,
    provenance_json TEXT,              -- archive ids, URLs, retrieval time...
    profile_json TEXT,
    mapping_json TEXT,                 -- user column/unit overrides
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    module_id TEXT NOT NULL,
    params_json TEXT,
    status TEXT NOT NULL,              -- queued | running | succeeded | failed
    stage TEXT,
    progress REAL DEFAULT 0,
    error TEXT,
    result_json TEXT,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    source TEXT,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS recent_targets (
    target_key TEXT PRIMARY KEY,
    label TEXT,
    kind TEXT,
    visited_at REAL NOT NULL
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(get_settings().db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as c:
        c.executescript(SCHEMA)


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=_json_default)


def _json_default(o: Any) -> Any:
    import numpy as np
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        v = float(o)
        return None if v != v or v in (float("inf"), float("-inf")) else v
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, tuple)):
        return list(o)
    raise TypeError(f"not JSON serializable: {type(o)}")


def now() -> float:
    return time.time()


# --- cache -----------------------------------------------------------------------------
def cache_get(key: str, max_age_s: float | None = None) -> tuple[Any, float] | None:
    ttl = get_settings().cache_ttl_hours * 3600 if max_age_s is None else max_age_s
    with connect() as c:
        row = c.execute("SELECT payload, fetched_at FROM cache WHERE key=?", (key,)).fetchone()
    if row is None or now() - row["fetched_at"] > ttl:
        return None
    return json.loads(row["payload"]), row["fetched_at"]


def cache_put(key: str, payload: Any, source: str) -> float:
    ts = now()
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO cache(key, payload, source, fetched_at) VALUES (?,?,?,?)",
            (key, dumps(payload), source, ts),
        )
    return ts
