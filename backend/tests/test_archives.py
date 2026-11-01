"""Archive clients against mocked transports (offline). Response bodies are hand-written to match
the documented formats and are NOT astronomical data; live behaviour is checked by
`pytest -m live` / scripts/verify_archives.py on a machine with network access."""
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.archives import base, exomast, mast, nasa
from app.archives.base import ArchiveError
from app.services import targets

HOST_ROWS = [{"pl_name": "Test-1 b", "hostname": "Test-1", "sy_pnum": 2, "discoverymethod": "Transit", "disc_year": 2012,
              "disc_facility": "Kepler", "pl_orbper": 3.5, "pl_orbpererr1": 0.001, "pl_orbpererr2": -0.001,
              "pl_rade": 2.0, "pl_trandur": 2.5, "ra": 10.5, "dec": -5.25, "st_teff": 5600, "st_rad": 0.95,
              "st_raderr1": 0.03, "st_raderr2": -0.03, "tic_id": "TIC 12345", "hd_name": None, "sy_snum": 1,
              "pl_refname": "Someone et al. 2020"},
             {"pl_name": "Test-1 c", "hostname": "Test-1", "pl_orbper": 11.2, "pl_rade": 3.1, "ra": 10.5, "dec": -5.25,
              "tic_id": "TIC 12345", "st_rad": 0.95, "st_teff": 5600}]


def router(handlers):
    def h(request: httpx.Request):
        for pred, resp in handlers:
            if pred(request):
                return resp(request) if callable(resp) else resp
        return httpx.Response(404, text="no mock")
    return httpx.MockTransport(h)


def tap(predicate_text, rows, status=200):
    return (lambda r: "TAP/sync" in str(r.url) and predicate_text in parse_qs(urlparse(str(r.url)).query)["query"][0].lower(),
            httpx.Response(status, json=rows) if status == 200 else httpx.Response(status, text="boom"))


def test_parse_identifiers():
    assert nasa.parse_identifier("TIC 261136679") == {"type": "tic", "id": 261136679}
    assert nasa.parse_identifier("toi-700") == {"type": "toi", "id": 700}
    assert nasa.parse_identifier("KIC 8462852") == {"type": "kic", "id": 8462852}
    assert nasa.parse_identifier("KOI-7")["type"] == "koi"
    assert nasa.parse_identifier("WASP-18")["type"] == "name"


def test_adql_literal_blocks_injection():
    lit = base.adql_literal("x'; drop table ps; --")
    assert ";" not in lit
    assert lit.startswith("'") and lit.endswith("'")
    inner = lit[1:-1]
    assert "'" not in inner.replace("''", "")   # any remaining quote is doubled (escaped)


def test_nasa_search_groups_planets_by_host():
    rows = [{"pl_name": "Test-1 b", "hostname": "Test-1", "sy_pnum": 2, "tic_id": "TIC 12345"},
            {"pl_name": "Test-1 c", "hostname": "Test-1", "sy_pnum": 2, "tic_id": "TIC 12345"}]
    base.set_transport(router([tap("from pscomppars", rows)]))
    r = nasa.search("test-1")
    assert [h["host"] for h in r["results"]] == ["Test-1"]
    assert r["results"][0]["planets"] == ["Test-1 b", "Test-1 c"]
    assert r["provenance"]["source"] == "nasa_search" and r["provenance"]["from_cache"] is False
    assert nasa.search("test-1")["provenance"]["from_cache"] is True   # second call served from cache


def test_host_system_separates_star_and_planets_with_units():
    base.set_transport(router([tap("from pscomppars where hostname", HOST_ROWS)]))
    s = nasa.host_system("Test-1")
    assert s["star"]["name"] == "Test-1" and s["star"]["radius"]["unit"] == "R_sun"
    assert [p["name"] for p in s["planets"]] == ["Test-1 b", "Test-1 c"]
    assert all(p["status"] == "confirmed" for p in s["planets"])
    assert s["planets"][0]["period"] == {"value": 3.5, "unit": "d", "err_plus": 0.001, "err_minus": -0.001}
    assert s["planets"][1]["mass"] is None   # missing values stay missing, never invented


def test_http_error_and_malformed_and_timeout():
    base.set_transport(router([tap("pscomppars", [], status=500)]))
    with pytest.raises(ArchiveError) as e:
        nasa.search("abc")
    assert e.value.retriable and e.value.status == 500

    base.set_transport(router([(lambda r: True, httpx.Response(200, text="<html>not json</html>"))]))
    with pytest.raises(ArchiveError) as e:
        nasa.search("abd")
    assert "JSON" in e.value.message

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)
    base.set_transport(httpx.MockTransport(timeout))
    with pytest.raises(ArchiveError) as e:
        nasa.search("abe")
    assert e.value.retriable and "timed out" in e.value.message


def test_offline_mode_refuses_network(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "offline", True)
    with pytest.raises(ArchiveError) as e:
        nasa.search("anything")
    assert "offline" in e.value.message.lower()


def test_mast_name_lookup_parses_documented_shape():
    body = {"resolvedCoordinate": [{"canonicalName": "M8", "ra": 270.9, "decl": -24.4, "objectType": "Nebula",
                                    "resolver": "NED"}], "status": "COMPLETE"}

    def check(r: httpx.Request):
        req = json.loads(parse_qs(r.content.decode())["request"][0])
        assert req["service"] == "Mast.Name.Lookup" and req["params"]["input"] == "m8"
        return httpx.Response(200, json=body)
    base.set_transport(router([(lambda r: "api/v0/invoke" in str(r.url), check)]))
    hit = mast.name_lookup("m8")
    assert hit["ra_deg"] == 270.9 and hit["dec_deg"] == -24.4 and hit["canonical_name"] == "M8"
    base.set_transport(router([(lambda r: "invoke" in str(r.url), httpx.Response(200, json={"resolvedCoordinate": []}))]))
    assert mast.name_lookup("nonexistent-xyz") is None


class FakeObs:
    """Stands in for astroquery.mast.Observations."""
    def __init__(self, rows, products):
        from astropy.table import Table
        self.obs = Table(rows=rows) if rows else Table(names=["obsid"], dtype=["i8"])
        self.prod = Table(rows=products) if products else Table(names=["productFilename"], dtype=["U10"])

    def query_criteria(self, **kw):
        assert "TESS" in kw["obs_collection"] and kw["dataproduct_type"] == "timeseries"
        return self.obs

    def get_product_list(self, obsid):
        return self.prod

    def download_file(self, uri, local_path, cache):
        open(local_path, "wb").write(b"SIMPLE  = T")
        return "COMPLETE", None, None


OBS_ROWS = [{"obsid": 1001, "obs_id": "tess-s0001", "obs_collection": "TESS", "provenance_name": "SPOC", "target_name": "12345",
             "sequence_number": 1, "instrument_name": "Photometer", "t_exptime": 120.0, "t_min": 58325.3, "t_max": 58353.2},
            {"obsid": 1002, "obs_id": "tess-qlp", "obs_collection": "TESS", "provenance_name": "QLP", "target_name": "12345",
             "sequence_number": 2, "instrument_name": "Photometer", "t_exptime": 1800.0, "t_min": 58354.0, "t_max": 58380.0}]
PROD_ROWS = [{"productFilename": "tess-s0001-0000000000012345-0120-s_lc.fits", "dataURI": "mast:TESS/product/tess-s0001_lc.fits",
              "size": 2_000_000, "description": "Light curves", "productSubGroupDescription": "LC"},
             {"productFilename": "tess-s0001_dv.pdf", "dataURI": "mast:TESS/product/dv.pdf", "size": 10, "description": "dv",
              "productSubGroupDescription": "DVR"}]


def test_mast_observations_flag_unsupported_pipelines(monkeypatch):
    monkeypatch.setattr(mast, "_obs", lambda: FakeObs(OBS_ROWS, PROD_ROWS))
    r = mast.find_observations(10.5, -5.25)
    by = {o["obsid"]: o for o in r["observations"]}
    assert by["1001"]["analysis_supported"] and by["1001"]["start_date"].startswith("2018")
    assert not by["1002"]["analysis_supported"] and "SPOC" in by["1002"]["unsupported_reason"]


def test_mast_product_filter_and_download_guards(monkeypatch, tmp_path):
    monkeypatch.setattr(mast, "_obs", lambda: FakeObs(OBS_ROWS, PROD_ROWS))
    prods = mast.list_light_curve_products("1001")["products"]
    assert [p["filename"] for p in prods] == ["tess-s0001-0000000000012345-0120-s_lc.fits"]   # DV PDF excluded
    p = mast.download_product(prods[0]["uri"], prods[0]["size_bytes"], tmp_path)
    assert p.exists()
    with pytest.raises(ArchiveError, match="above the"):
        mast.download_product("mast:TESS/product/big_lc.fits", 10**10, tmp_path)
    with pytest.raises(ArchiveError, match="unexpected product URI"):
        mast.download_product("http://evil.example/x_lc.fits", 10, tmp_path)
    with pytest.raises(ArchiveError):
        mast.download_product("mast:../../etc/passwd", 10, tmp_path)


def test_exomast_defensive_parsing():
    payload = {"canonical_name": "Test-1 b", "planet_names": ["Test-1 b", "KOI-1.01"], "star_name": "Test-1"}
    base.set_transport(router([(lambda r: "exoplanets/identifiers" in str(r.url), httpx.Response(200, json=payload))]))
    r = exomast.identifiers("koi-1.01")
    assert "KOI-1.01" in r["aliases"] and "Test-1" in r["aliases"]
    base.set_transport(router([(lambda r: True, httpx.Response(404))]))
    assert exomast.identifiers("zzz-404") is None


def test_target_detail_partial_results_when_one_archive_fails(monkeypatch):
    monkeypatch.setattr(mast, "_obs", lambda: (_ for _ in ()).throw(RuntimeError("MAST down")))
    base.set_transport(router([tap("from pscomppars where hostname", HOST_ROWS),
                               tap("from toi where tid", [{"toi": 123.01, "tid": 12345, "tfopwg_disp": "PC", "pl_orbper": 11.2}]),
                               (lambda r: "exoplanets/identifiers" in str(r.url), httpx.Response(200, json={"names": ["Test-1 b"]}))]))
    d = targets.detail("host:Test-1")
    assert [p["name"] for p in d["published_planets"]] == ["Test-1 b", "Test-1 c"]
    assert d["catalog_candidates"][0]["status"] == "candidate" and d["catalog_candidates"][0]["disposition"] == "PC"
    assert d["observations"] == {} and d["n_observations"] == 0
    assert any(e["source"] == "MAST" for e in d["errors"])     # failure reported, not hidden
    assert d["provenance"] and all("retrieved_at" in p for p in d["provenance"])
    kp = targets.known_planets_for_analysis(d)
    assert {k["status"] for k in kp} == {"published", "candidate"}


def test_target_with_catalogue_entry_but_no_observations(monkeypatch):
    monkeypatch.setattr(mast, "_obs", lambda: FakeObs([], []))
    base.set_transport(router([tap("from pscomppars where hostname", HOST_ROWS),
                               tap("from toi where tid", []),
                               (lambda r: "exoplanets/identifiers" in str(r.url), httpx.Response(404))]))
    d = targets.detail("host:Test-1")
    assert d["published_planets"] and d["n_observations"] == 0 and not d["errors"]
    assert any("does not imply" in n for n in d["notes"])


@pytest.mark.live
def test_live_nasa_tap_reachable():
    base.set_transport(None)
    rows = nasa.tap_query("select top 1 pl_name, hostname from pscomppars")
    assert rows and "pl_name" in rows[0]
