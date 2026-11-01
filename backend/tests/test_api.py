"""API integration: upload → profile → analysis job → exports, plus failure paths."""
import hashlib
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import db
from app.archives import base, mast
from app.config import get_settings
from app.services import datasets, jobs
from app.synthetic import make_lightcurve
from tests.test_archives import FakeObs, HOST_ROWS, OBS_ROWS, PROD_ROWS, router, tap


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "RUN_JOBS_INLINE", True)
    with TestClient(main.app) as c:
        yield c


def lc_csv(seed=1, period=3.2, rp=0.05, baseline=20, cadence=10):
    lc, _ = make_lightcurve(period=period, rp=rp, noise_ppm=500, seed=seed, baseline=baseline, cadence_min=cadence)
    body = "time,flux,flux_err\n" + "\n".join(f"{t:.6f},{f:.7f},{e:.7f}" for t, f, e in zip(lc.time, lc.flux, lc.flux_err))
    return body.encode()


def upload(client, body, name="lc.csv"):
    return client.post("/api/datasets/upload", files={"file": (name, body, "text/csv")})


def test_health_and_modules(client):
    assert client.get("/api/health").json()["status"] == "ok"
    mods = {m["id"]: m for m in client.get("/api/modules").json()}
    assert mods["transit_bls"]["status"] == "available"
    assert all(mods[k]["status"] == "planned" for k in ("rv_periodogram", "transmission_spectroscopy", "direct_imaging", "astrometric_orbit"))
    assert mods["transit_bls"]["limitations"] and mods["transit_bls"]["validation_tests"]


def test_upload_to_results_and_exports(client):
    body = lc_csv()
    r = upload(client, body)
    assert r.status_code == 200
    ds = r.json()
    assert ds["profile"]["category"] == "photometric_time_series"
    assert ds["sha256"] == hashlib.sha256(body).hexdigest()
    assert ds["analysis_options"][0]["status"] == "available"
    pv = client.get(f"/api/datasets/{ds['id']}/preview").json()
    assert pv["kind"] == "lightcurve" and pv["n_points"] > 1000

    a = client.post("/api/analyses", json={"dataset_id": ds["id"], "params": {"max_candidates": 1}})
    assert a.status_code == 202
    res = client.get(f"/api/analyses/{a.json()['id']}").json()
    assert res["status"] == "succeeded", res
    prov = res["result"]["provenance"]
    assert prov["dataset"]["sha256"] == ds["sha256"]              # result is tied to its exact input
    assert prov["input_schema"]["roles"]["flux"]["column"] == "flux"
    assert prov["versions"]["astropy"] and prov["parameters"]["max_candidates"] == 1
    c = res["result"]["candidates"][0]
    assert abs(c["period"] - 3.2) < 0.02 and c["kind"] == "new_unvalidated_signal"

    aid = res["id"]
    assert json.loads(client.get(f"/api/analyses/{aid}/export.json").text)["result"]["candidates"]
    csv = client.get(f"/api/analyses/{aid}/candidates.csv").text.splitlines()
    assert csv[0].startswith("rank,classification") and len(csv) >= 2
    rep = client.get(f"/api/analyses/{aid}/report.html").text
    assert "None is a confirmed or validated" in rep and "sha256" in rep and "<img" in rep
    assert any(x["id"] == aid for x in client.get("/api/analyses").json())


def test_reproducible_same_input_same_result(client):
    ds = upload(client, lc_csv(seed=4)).json()
    out = []
    for _ in range(2):
        a = client.post("/api/analyses", json={"dataset_id": ds["id"], "params": {"max_candidates": 1, "fit": False}}).json()
        r = client.get(f"/api/analyses/{a['id']}").json()["result"]["candidates"][0]
        out.append((r["period"], r["t0"], r["sde"]))
    assert out[0] == out[1]


def test_upload_rejections(client):
    assert upload(client, b"MZ\x90\x00", "evil.exe").status_code == 422
    r = upload(client, b"", "empty.csv")
    assert r.status_code == 422 and "empty" in r.json()["message"]
    r = upload(client, b"\x00\x01\x02" * 400, "bin.csv")
    assert r.status_code == 422
    r = upload(client, b"SIMPLE  =                    T" + b"x" * 100, "bad.fits")
    assert r.status_code == 422 and "FITS" in r.json()["message"]
    r = upload(client, b"x", "a.fits.gz")
    assert r.status_code == 422


def test_upload_size_limit(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    r = upload(client, b"time,flux\n" + b"1,1\n" * 400_000)
    assert r.status_code == 422 and "limit" in r.json()["message"]
    # nothing is left behind on disk for a rejected upload
    assert not any(p.is_dir() and not any(p.iterdir()) for p in get_settings().upload_dir.iterdir())


def test_filename_cannot_escape_storage(client):
    r = upload(client, lc_csv(), "../../../../tmp/pwn.csv")
    assert r.status_code == 200
    stored = datasets.get_dataset(r.json()["id"])["stored_path"]
    assert str(get_settings().upload_dir) in stored and ".." not in stored


def test_unsupported_data_cannot_be_analysed(client):
    rv = "bjd,rv,rv_err\n" + "\n".join(f"{2458000 + i * 3.1},{i % 7},1.0" for i in range(40))
    ds = upload(client, rv.encode()).json()
    assert ds["profile"]["category"] == "radial_velocity"
    r = client.post("/api/analyses", json={"dataset_id": ds["id"], "module_id": "rv_periodogram"})
    assert r.status_code == 422 and "not implemented" in r.json()["detail"]
    r = client.post("/api/analyses", json={"dataset_id": ds["id"], "module_id": "transit_bls"})
    assert r.status_code == 422 and "needs photometric" in r.json()["detail"]


def test_unsuitable_dataset_explained(client):
    short = "time,flux\n" + "\n".join(f"{i * 0.01},{1 + 1e-4 * (i % 3)}" for i in range(60))
    ds = upload(client, short.encode()).json()
    r = client.post("/api/analyses", json={"dataset_id": ds["id"]})
    assert r.status_code == 422 and "not suitable" in r.json()["detail"]


def test_column_mapping_override_flow(client):
    lc, _ = make_lightcurve(period=3.2, rp=0.05, noise_ppm=500, seed=1, baseline=20, cadence_min=10)
    body = "col_a,col_b,col_c\n" + "\n".join(f"{t:.6f},{f:.7f},{e:.7f}" for t, f, e in zip(lc.time, lc.flux, lc.flux_err))
    ds = upload(client, body.encode()).json()
    assert ds["profile"]["category"] == "unknown" and ds["profile"]["needs_confirmation"]
    fixed = client.post(f"/api/datasets/{ds['id']}/mapping",
                        json={"mapping": {"time": "col_a", "flux": "col_b", "flux_err": "col_c"}}).json()
    assert fixed["profile"]["category"] == "photometric_time_series"
    a = client.post("/api/analyses", json={"dataset_id": ds["id"], "params": {"max_candidates": 1, "fit": False}}).json()
    done = client.get(f"/api/analyses/{a['id']}").json()
    assert done["status"] == "succeeded"
    assert done["result"]["provenance"]["manual_mapping"]["flux"] == "col_b"   # manual choices are recorded


def test_exports_blocked_until_success_and_unknown_ids(client):
    assert client.get("/api/analyses/nope").status_code == 404
    assert client.get("/api/analyses/nope/report.html").status_code == 404
    assert client.get("/api/datasets/nope").status_code == 404
    aid = datasets.new_id()
    with db.connect() as c:
        c.execute("INSERT INTO analyses(id, dataset_id, module_id, params_json, status, created_at) VALUES (?,?,?,?,?,?)",
                  (aid, "x", "transit_bls", "{}", "running", db.now()))
    assert client.get(f"/api/analyses/{aid}/export.json").status_code == 409


def test_stale_running_jobs_are_failed_on_startup():
    aid = datasets.new_id()
    with db.connect() as c:
        c.execute("INSERT INTO analyses(id, dataset_id, module_id, params_json, status, created_at) VALUES (?,?,?,?,?,?)",
                  (aid, "x", "transit_bls", "{}", "running", db.now()))
    jobs.mark_stale_jobs()
    a = jobs.get(aid)
    assert a["status"] == "failed" and "restarted" in a["error"]


def test_job_failure_reports_reason(client):
    ds = upload(client, lc_csv()).json()
    a = client.post("/api/analyses", json={"dataset_id": ds["id"], "params": {"min_period": 50, "max_period": 60}}).json()
    done = client.get(f"/api/analyses/{a['id']}").json()
    assert done["status"] == "failed" and "too short" in done["error"].lower()


def test_expired_upload_cleanup(client, monkeypatch):
    ds = upload(client, lc_csv()).json()
    monkeypatch.setattr(get_settings(), "upload_ttl_hours", -1)
    assert datasets.cleanup_expired() >= 1
    assert client.get(f"/api/datasets/{ds['id']}/preview").status_code in (404, 410)


def test_client_cannot_inject_known_planets(client):
    ds = upload(client, lc_csv()).json()
    a = client.post("/api/analyses", json={"dataset_id": ds["id"], "params": {
        "max_candidates": 1, "fit": False, "known_planets": [{"name": "Fake b", "period": 3.2, "status": "published"}]}}).json()
    c = client.get(f"/api/analyses/{a['id']}").json()["result"]["candidates"][0]
    assert c["kind"] == "new_unvalidated_signal"       # server ignores client-supplied catalogue claims


# ---- archive-facing endpoints (mocked) ---------------------------------------------------------
def test_target_search_detail_and_import_flow(client, monkeypatch):
    rows = [{"pl_name": "Test-1 b", "hostname": "Test-1", "sy_pnum": 2, "tic_id": "TIC 12345"}]
    base.set_transport(router([
        tap("from pscomppars where hostname", HOST_ROWS), tap("from pscomppars where lower", rows),
        tap("from toi where tid", []), (lambda r: "exoplanets/identifiers" in str(r.url), httpx.Response(404))]))
    monkeypatch.setattr(mast, "_obs", lambda: FakeObs(OBS_ROWS, PROD_ROWS))
    s = client.get("/api/targets/search", params={"q": "test-1"}).json()
    assert s["results"][0]["key"] == "host:Test-1" and s["results"][0]["source"] == "NASA Exoplanet Archive"
    d = client.get("/api/targets/detail", params={"key": "host:Test-1"}).json()
    assert d["n_observations"] == 2 and d["published_planets"][0]["name"] == "Test-1 b"
    assert client.get("/api/targets/recent").json()[0]["target_key"] == "host:Test-1"
    prods = client.get("/api/observations/1001/products").json()["products"]
    assert len(prods) == 1

    # make the "downloaded" product a real TESS-format FITS file so the import goes through the shared pipeline
    from astropy.io import fits
    import numpy as np
    lc, _ = make_lightcurve(period=3.2, rp=0.05, noise_ppm=500, seed=1, baseline=20, cadence_min=10)
    cols = [fits.Column(name="TIME", format="D", array=lc.time), fits.Column(name="PDCSAP_FLUX", format="E", array=lc.flux * 1000),
            fits.Column(name="PDCSAP_FLUX_ERR", format="E", array=lc.flux_err * 1000),
            fits.Column(name="QUALITY", format="J", array=np.zeros(len(lc.time), dtype=int))]
    h0 = fits.PrimaryHDU()
    h0.header["TELESCOP"] = "TESS"
    h1 = fits.BinTableHDU.from_columns(cols, name="LIGHTCURVE")
    h1.header["BJDREFI"], h1.header["BJDREFF"] = 2457000, 0.0

    def fake_download(uri, size, dest):
        dest.mkdir(parents=True, exist_ok=True)
        p = dest / "tess_lc.fits"
        fits.HDUList([h0, h1]).writeto(p, overwrite=True)
        return p
    monkeypatch.setattr(mast, "download_product", fake_download)
    imp = client.post("/api/observations/import", json={"obsid": "1001", "uri": prods[0]["uri"], "filename": prods[0]["filename"],
                                                        "size_bytes": 1000, "target_label": "Test-1", "mission": "TESS"})
    assert imp.status_code == 200
    ds = imp.json()
    assert ds["source"] == "archive" and ds["provenance"]["obsid"] == "1001" and "retrieved_at" in ds["provenance"]
    a = client.post("/api/analyses", json={"dataset_id": ds["id"], "target_key": "host:Test-1", "params": {"max_candidates": 1, "fit": False}}).json()
    done = client.get(f"/api/analyses/{a['id']}").json()
    assert done["status"] == "succeeded"
    assert done["result"]["provenance"]["dataset"]["provenance"]["obsid"] == "1001"


def test_archive_failure_surfaces_as_error_not_crash(client):
    base.set_transport(router([tap("pscomppars", [], status=500), (lambda r: "invoke" in str(r.url), httpx.Response(503))]))
    s = client.get("/api/targets/search", params={"q": "wasp-18"}).json()
    assert s["results"] == [] and len(s["errors"]) >= 1 and s["errors"][0]["retriable"] is True


def test_bad_target_key_and_obsid(client):
    assert client.get("/api/targets/detail", params={"key": "garbage"}).status_code == 422
    assert client.get("/api/observations/abc/products").status_code == 422
