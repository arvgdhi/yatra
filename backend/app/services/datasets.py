"""Dataset lifecycle: safe upload storage, profiling, archive import, previews and cleanup.

Uploaded bytes are stored under a random id in an isolated directory, size-limited while
streaming, and are only ever parsed as data. The original file is never modified.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np

from .. import db
from ..config import get_settings
from ..ingest.loader import load_lightcurve
from ..ingest.profiler import build_profile
from ..ingest.reader import IngestError, read_table

ALLOWED_SUFFIXES = (".csv", ".txt", ".tsv", ".dat", ".fits", ".fit", ".fits.gz")


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def safe_display_name(name: str | None) -> str:
    base = Path(name or "upload").name
    return re.sub(r"[^A-Za-z0-9_.\- ]", "_", base)[:120] or "upload"


def save_upload(stream: BinaryIO, original_name: str | None) -> dict[str, Any]:
    """Stream an upload to disk, enforcing the size limit; returns the registered dataset record."""
    s = get_settings()
    name = safe_display_name(original_name)
    low = name.lower()
    if not low.endswith(ALLOWED_SUFFIXES):
        raise IngestError(f"Unsupported file type '{Path(name).suffix}'.",
                          "Supported: .csv, .tsv, .txt, .dat (tables) and .fits (light-curve or image files).")
    if low.endswith(".fits.gz"):
        raise IngestError("Compressed FITS (.fits.gz) is not accepted.", "Decompress it and upload the .fits file.")
    ds_id = new_id()
    d = s.upload_dir / ds_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / ("data" + (".fits" if low.endswith((".fits", ".fit")) else ".txt"))
    h = hashlib.sha256()
    size = 0
    try:
        with open(path, "wb") as out:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > s.max_upload_bytes:
                    raise IngestError(f"File exceeds the {s.max_upload_mb} MB upload limit.",
                                      "Subset or bin the data, or raise EXPLORER_MAX_UPLOAD_MB on your own deployment.")
                h.update(chunk)
                out.write(chunk)
        if size == 0:
            raise IngestError("The uploaded file is empty.")
        table = read_table(path)
        profile = build_profile(table)
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return _register(ds_id, "upload", name, path, h.hexdigest(), size, {"original_name": name}, profile)


def _register(ds_id, source, name, path, sha, size, provenance, profile) -> dict[str, Any]:
    with db.connect() as c:
        c.execute(
            "INSERT INTO datasets(id, source, original_name, stored_path, sha256, size_bytes, provenance_json, "
            "profile_json, mapping_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ds_id, source, name, str(path), sha, size, db.dumps(provenance), db.dumps(profile), "{}", db.now()))
    return get_dataset(ds_id)


def import_archive_file(path: Path, display_name: str, provenance: dict[str, Any]) -> dict[str, Any]:
    """Register a file already downloaded from an archive as a dataset (copy into isolated storage)."""
    s = get_settings()
    ds_id = new_id()
    d = s.upload_dir / ds_id
    d.mkdir(parents=True, exist_ok=True)
    dest = d / "data.fits"
    shutil.copyfile(path, dest)
    sha = hashlib.sha256(dest.read_bytes()).hexdigest()
    try:
        profile = build_profile(read_table(dest))
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return _register(ds_id, "archive", display_name, dest, sha, dest.stat().st_size, provenance, profile)


def get_dataset(ds_id: str) -> dict[str, Any]:
    with db.connect() as c:
        row = c.execute("SELECT * FROM datasets WHERE id=?", (ds_id,)).fetchone()
    if row is None:
        raise KeyError(ds_id)
    return {
        "id": row["id"], "source": row["source"], "name": row["original_name"], "sha256": row["sha256"],
        "size_bytes": row["size_bytes"], "provenance": json.loads(row["provenance_json"] or "{}"),
        "profile": json.loads(row["profile_json"] or "{}"), "mapping": json.loads(row["mapping_json"] or "{}"),
        "created_at": row["created_at"], "stored_path": row["stored_path"],
    }


def public(ds: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in ds.items() if k != "stored_path"}


def set_mapping(ds_id: str, mapping: dict[str, Any]) -> dict[str, Any]:
    ds = get_dataset(ds_id)
    clean = {k: v for k, v in mapping.items() if isinstance(k, str) and isinstance(v, (str, int, float))}
    table = read_table(Path(ds["stored_path"]))
    profile = build_profile(table, clean)
    with db.connect() as c:
        c.execute("UPDATE datasets SET mapping_json=?, profile_json=? WHERE id=?", (db.dumps(clean), db.dumps(profile), ds_id))
    return public(get_dataset(ds_id))


def load_for_analysis(ds_id: str):
    ds = get_dataset(ds_id)
    return load_lightcurve(Path(ds["stored_path"]), ds["mapping"]), ds


def preview(ds_id: str, max_points: int = 5000) -> dict[str, Any]:
    ds = get_dataset(ds_id)
    if ds["profile"].get("category") != "photometric_time_series" and not (
            {"time", "flux"} <= set(ds["profile"].get("roles", {}))):
        return {"kind": "none", "reason": "Preview is available for photometric time series only."}
    lc, prof = load_lightcurve(Path(ds["stored_path"]), ds["mapping"])
    ok = np.isfinite(lc.time) & np.isfinite(lc.flux)
    t, y = lc.time[ok], lc.flux[ok]
    if len(t) > max_points:
        idx = np.linspace(0, len(t) - 1, max_points).astype(int)
        t, y = t[idx], y[idx]
    return {"kind": "lightcurve", "time": t.tolist(), "flux": y.tolist(), "time_format": lc.time_format,
            "time_offset_jd": lc.time_offset_jd, "n_points": int(ok.sum()), "n_shown": int(len(t))}


def cleanup_expired() -> int:
    """Remove uploaded datasets (and their files) older than the TTL. Archive-derived files are
    re-downloadable and are cleaned with the same rule; analyses keep their own result JSON."""
    s = get_settings()
    cutoff = db.now() - s.upload_ttl_hours * 3600
    with db.connect() as c:
        rows = c.execute("SELECT id, stored_path FROM datasets WHERE created_at < ?", (cutoff,)).fetchall()
        for r in rows:
            shutil.rmtree(Path(r["stored_path"]).parent, ignore_errors=True)
            c.execute("UPDATE datasets SET stored_path=NULL WHERE id=?", (r["id"],))
    return len(rows)
