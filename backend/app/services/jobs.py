"""Analysis jobs: executed in separate worker processes so numerical work never blocks the API.

State lives in SQLite (status, stage, progress, result), so the API process only reads it and a
worker crash cannot take the server down. Each job records the dataset identity, parameters,
library versions and warnings alongside its result.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import traceback
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from .. import db
from ..config import get_settings
from ..versions import dependency_versions

_POOL: ProcessPoolExecutor | None = None


def _pool() -> ProcessPoolExecutor:
    global _POOL
    if _POOL is None:
        _POOL = ProcessPoolExecutor(max_workers=get_settings().max_workers, mp_context=mp.get_context("spawn"))
    return _POOL


def shutdown() -> None:
    global _POOL
    if _POOL is not None:
        _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL = None


def mark_stale_jobs() -> None:
    """Jobs left 'running' by a previous server process cannot still be running."""
    with db.connect() as c:
        c.execute("UPDATE analyses SET status='failed', error='Server restarted while the job was running', "
                  "finished_at=? WHERE status IN ('queued','running')", (db.now(),))


def create(dataset_id: str, module_id: str, params: dict[str, Any]) -> str:
    from ..analysis.registry import get_module
    from . import datasets
    mod = get_module(module_id)
    if mod.status != "available" or mod.run is None:
        raise ValueError(f"Analysis module '{module_id}' is {mod.status}, not implemented.")
    ds = datasets.get_dataset(dataset_id)
    if ds["profile"].get("category") != mod.category:
        raise ValueError(f"'{mod.name}' needs {mod.category.replace('_', ' ')} data, but this dataset was classified as "
                         f"{ds['profile'].get('category_label', 'unknown')}. Correct the column mapping if that is wrong.")
    info = next((m for m in ds["profile"]["applicable_methods"] if m["id"] == module_id), None)
    if info and info["status"] == "unsuitable":
        raise ValueError(f"This dataset is not suitable for {mod.name}: {info.get('reason')}")
    aid = datasets.new_id()
    with db.connect() as c:
        c.execute("INSERT INTO analyses(id, dataset_id, module_id, params_json, status, stage, progress, created_at) "
                  "VALUES (?,?,?,?,?,?,?,?)", (aid, dataset_id, module_id, db.dumps(params), "queued", "Queued", 0.0, db.now()))
    return aid


def submit(aid: str, inline: bool = False) -> None:
    if inline:
        run_job(aid)
    else:
        _pool().submit(run_job, aid)


def _update(aid: str, **fields: Any) -> None:
    cols = ", ".join(f"{k}=?" for k in fields)
    with db.connect() as c:
        c.execute(f"UPDATE analyses SET {cols} WHERE id=?", (*fields.values(), aid))


def run_job(aid: str) -> None:
    """Worker entry point (runs in a separate process)."""
    from ..analysis.registry import get_module
    from . import datasets
    db.init_db()
    with db.connect() as c:
        row = c.execute("SELECT * FROM analyses WHERE id=?", (aid,)).fetchone()
    if row is None:
        return
    _update(aid, status="running", stage="Loading data", progress=0.01, started_at=db.now())
    last = {"t": 0.0}

    def progress(p: float, msg: str) -> None:
        now = db.now()
        if now - last["t"] > 0.4 or p >= 0.97:
            last["t"] = now
            _update(aid, progress=float(p), stage=msg)

    try:
        params = json.loads(row["params_json"] or "{}")
        (lc, profile), ds = datasets.load_for_analysis(row["dataset_id"])
        mod = get_module(row["module_id"])
        result = mod.run(lc, params, progress)
        result["provenance"].update({
            "dataset": {"id": ds["id"], "name": ds["name"], "source": ds["source"], "sha256": ds["sha256"],
                        "provenance": ds["provenance"]},
            "input_schema": {"roles": profile["roles"], "time": profile["time"], "flux_kind": profile["flux_kind"],
                             "category": profile["category"], "confidence": profile["confidence"]},
            "manual_mapping": ds["mapping"], "input_quality_issues": profile["quality_issues"],
            "versions": dependency_versions(), "module": row["module_id"], "analysis_id": aid,
            "uncertainties_estimated_from_scatter": bool(profile.get("uncertainties_estimated")),
        })
        _update(aid, status="succeeded", stage="Done", progress=1.0, result_json=db.dumps(result), finished_at=db.now())
    except Exception as e:  # report every failure with its reason
        msg = str(e) or e.__class__.__name__
        _update(aid, status="failed", stage="Failed", error=msg, finished_at=db.now(),
                result_json=db.dumps({"traceback": traceback.format_exc()[-2000:]}))


def get(aid: str, include_result: bool = True) -> dict[str, Any]:
    with db.connect() as c:
        row = c.execute("SELECT * FROM analyses WHERE id=?", (aid,)).fetchone()
    if row is None:
        raise KeyError(aid)
    out = {"id": row["id"], "dataset_id": row["dataset_id"], "module_id": row["module_id"],
           "params": json.loads(row["params_json"] or "{}"), "status": row["status"], "stage": row["stage"],
           "progress": row["progress"], "error": row["error"], "created_at": row["created_at"],
           "started_at": row["started_at"], "finished_at": row["finished_at"]}
    if include_result and row["status"] == "succeeded" and row["result_json"]:
        out["result"] = json.loads(row["result_json"])
    return out


def list_all(limit: int = 100) -> list[dict[str, Any]]:
    with db.connect() as c:
        rows = c.execute(
            "SELECT a.id, a.dataset_id, a.module_id, a.status, a.created_at, a.finished_at, a.error, d.original_name, d.source "
            "FROM analyses a LEFT JOIN datasets d ON d.id=a.dataset_id ORDER BY a.created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
