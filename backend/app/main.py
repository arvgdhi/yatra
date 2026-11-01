"""FastAPI application: one API for both entry points (upload and archive target exploration)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from . import db
from .analysis.registry import REGISTRY, applicable_modules
from .archives import mast
from .archives.base import ArchiveError
from .config import get_settings
from .ingest.reader import IngestError
from .services import datasets, jobs, report, targets


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings().ensure_dirs()
    db.init_db()
    jobs.mark_stale_jobs()
    datasets.cleanup_expired()
    yield
    jobs.shutdown()


app = FastAPI(title="Exoplanet Explorer API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
                   allow_methods=["*"], allow_headers=["*"])

# Set by tests to run jobs synchronously in-process.
RUN_JOBS_INLINE = False


@app.exception_handler(IngestError)
async def _ingest_err(_, exc: IngestError):
    return JSONResponse(status_code=422, content={"error": "invalid_file", "message": exc.message, "hint": exc.hint})


@app.exception_handler(ArchiveError)
async def _archive_err(_, exc: ArchiveError):
    return JSONResponse(status_code=502 if exc.retriable else 424, content={"error": "archive_error", **exc.to_dict()})


@app.get("/api/health")
def health():
    s = get_settings()
    return {"status": "ok", "app_name": s.app_name, "offline": s.offline, "max_upload_mb": s.max_upload_mb}


@app.get("/api/config")
def config():
    s = get_settings()
    return {"app_name": s.app_name, "offline": s.offline, "max_upload_mb": s.max_upload_mb,
            "supported_formats": [".csv", ".tsv", ".txt", ".dat", ".fits"], "upload_ttl_hours": s.upload_ttl_hours}


# ---- modules ------------------------------------------------------------------------------
@app.get("/api/modules")
def modules():
    return [m.describe() for m in REGISTRY.values()]


# ---- datasets -----------------------------------------------------------------------------
@app.post("/api/datasets/upload")
async def upload(file: UploadFile = File(...)):
    ds = datasets.save_upload(file.file, file.filename)
    return _dataset_response(ds)


def _dataset_response(ds: dict[str, Any]) -> dict[str, Any]:
    out = datasets.public(ds)
    out["analysis_options"] = applicable_modules(ds["profile"]) if ds["profile"].get("category") else []
    return out


@app.get("/api/datasets/{ds_id}")
def get_dataset(ds_id: str):
    try:
        return _dataset_response(datasets.get_dataset(ds_id))
    except KeyError:
        raise HTTPException(404, "Dataset not found")


class MappingBody(BaseModel):
    mapping: dict[str, Any]


@app.post("/api/datasets/{ds_id}/mapping")
def set_mapping(ds_id: str, body: MappingBody):
    try:
        datasets.set_mapping(ds_id, body.mapping)
        return _dataset_response(datasets.get_dataset(ds_id))
    except KeyError:
        raise HTTPException(404, "Dataset not found")
    except FileNotFoundError:
        raise HTTPException(410, "The stored file has expired; please upload it again.")


@app.get("/api/datasets/{ds_id}/preview")
def preview(ds_id: str):
    try:
        return datasets.preview(ds_id)
    except KeyError:
        raise HTTPException(404, "Dataset not found")
    except (FileNotFoundError, TypeError):
        raise HTTPException(410, "The stored file has expired; please upload it again.")


# ---- analyses -----------------------------------------------------------------------------
class AnalysisBody(BaseModel):
    dataset_id: str
    module_id: str = "transit_bls"
    params: dict[str, Any] = {}
    target_key: str | None = None   # lets the server attach catalogue planets for comparison


@app.post("/api/analyses", status_code=202)
def start_analysis(body: AnalysisBody):
    params = dict(body.params)
    # Known planets/candidates are always taken from the archive record, never from the client.
    params.pop("known_planets", None)
    if body.target_key:
        try:
            params["known_planets"] = targets.known_planets_for_analysis(targets.detail(body.target_key))
        except Exception:
            params["known_planets"] = []
    try:
        aid = jobs.create(body.dataset_id, body.module_id, params)
    except KeyError:
        raise HTTPException(404, "Dataset or module not found")
    except ValueError as e:
        raise HTTPException(422, str(e))
    jobs.submit(aid, inline=RUN_JOBS_INLINE)
    return jobs.get(aid, include_result=False)


@app.get("/api/analyses")
def list_analyses():
    return jobs.list_all()


@app.get("/api/analyses/{aid}")
def get_analysis(aid: str):
    try:
        return jobs.get(aid)
    except KeyError:
        raise HTTPException(404, "Analysis not found")


def _succeeded(aid: str) -> dict[str, Any]:
    try:
        a = jobs.get(aid)
    except KeyError:
        raise HTTPException(404, "Analysis not found")
    if a["status"] != "succeeded":
        raise HTTPException(409, f"Analysis is {a['status']}; exports are available once it has succeeded.")
    return a


@app.get("/api/analyses/{aid}/export.json")
def export_json(aid: str):
    a = _succeeded(aid)
    return Response(report.export_json(a), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="analysis_{aid}.json"'})


@app.get("/api/analyses/{aid}/candidates.csv")
def export_csv(aid: str):
    a = _succeeded(aid)
    return Response(report.candidates_csv(a), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="candidates_{aid}.csv"'})


@app.get("/api/analyses/{aid}/report.html")
def export_report(aid: str):
    a = _succeeded(aid)
    return Response(report.report_html(a, get_settings().app_name), media_type="text/html",
                    headers={"Content-Disposition": f'attachment; filename="report_{aid}.html"'})


# ---- targets ------------------------------------------------------------------------------
@app.get("/api/targets/search")
def search_targets(q: str):
    return targets.search(q)


@app.get("/api/targets/recent")
def recent_targets():
    return targets.recent()


@app.get("/api/targets/detail")
def target_detail(key: str):
    try:
        return targets.detail(key)
    except (ValueError, IndexError):
        raise HTTPException(422, "Malformed target key")


@app.get("/api/observations/{obsid}/products")
def observation_products(obsid: str):
    if not obsid.isdigit():
        raise HTTPException(422, "obsid must be numeric")
    return mast.list_light_curve_products(obsid)


class ImportBody(BaseModel):
    obsid: str
    uri: str
    filename: str
    size_bytes: int | None = None
    target_label: str | None = None
    mission: str | None = None


@app.post("/api/observations/import")
def import_observation(body: ImportBody):
    """Download one archive light-curve product and register it as a dataset (same path as uploads)."""
    s = get_settings()
    path = mast.download_product(body.uri, body.size_bytes, s.data_dir / "archive_cache")
    from datetime import datetime, timezone
    prov = {"archive": "MAST", "obsid": body.obsid, "product_uri": body.uri, "filename": body.filename,
            "target": body.target_label, "mission": body.mission,
            "retrieved_at": datetime.now(timezone.utc).isoformat()}
    ds = datasets.import_archive_file(Path(path), body.filename, prov)
    return _dataset_response(ds)
