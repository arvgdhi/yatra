"""Data ingestion and dataset classification."""
import numpy as np
import pytest
from astropy.io import fits

from app.ingest.loader import load_lightcurve
from app.ingest.profiler import build_profile
from app.ingest.reader import IngestError, read_table
from app.synthetic import make_lightcurve
from tests.conftest import write_csv


def test_standard_csv_is_photometric(tmp_path, clean_lc):
    lc, _ = clean_lc
    p = write_csv(tmp_path / "a.csv", lc)
    prof = build_profile(read_table(p))
    assert prof["category"] == "photometric_time_series"
    assert prof["confidence"] >= 0.6 and not prof["needs_confirmation"]
    assert prof["applicable_methods"][0]["status"] == "available"
    assert any(e["kind"] == "classification" for e in prof["evidence"])


@pytest.mark.parametrize("header", [("BJD_TDB", "norm_flux", "flux_unc"), ("Time [BTJD]", "PDCSAP_FLUX", "PDCSAP_FLUX_ERR"),
                                    ("bjd", "photometric_index", "eflux")])
def test_column_aliases(tmp_path, clean_lc, header):
    lc, _ = clean_lc
    # photometric_index is not a known alias: expected to need confirmation; the others classify directly
    p = write_csv(tmp_path / "a.csv", lc, header=header, time_shift=2457000.0 if "BJD" in header[0].upper() else 0)
    prof = build_profile(read_table(p))
    if header[1] == "photometric_index":
        assert "flux" not in prof["roles"]
        prof = build_profile(read_table(p), {"flux": "photometric_index"})
    assert prof["category"] == "photometric_time_series"


def test_time_in_hours_is_converted(tmp_path, clean_lc):
    lc, _ = clean_lc
    p = write_csv(tmp_path / "h.csv", lc, header=("time [h]", "flux", "flux_err"), time_scale=24.0)
    out, prof = load_lightcurve(p)
    assert np.isclose(out.time.max(), lc.time.max(), rtol=1e-6)
    assert prof["time"]["unit"] == "h"


def test_bjd_offset_detected(tmp_path, clean_lc):
    lc, _ = clean_lc
    p = write_csv(tmp_path / "j.csv", lc, header=("BJD", "flux", "flux_err"), time_shift=2459000.0)
    prof = build_profile(read_table(p))
    assert prof["time"]["format"] == "bjd" and prof["time"]["offset_jd"] == 0.0


def test_magnitudes_converted_to_relative_flux(tmp_path, clean_lc):
    lc, _ = clean_lc
    mag = 12.0 - 2.5 * np.log10(lc.flux)
    p = tmp_path / "m.csv"
    with open(p, "w") as f:
        f.write("time,mag,magerr\n")
        for t, m in zip(lc.time, mag):
            f.write(f"{t:.6f},{m:.7f},0.0005\n")
    out, prof = load_lightcurve(p)
    assert prof["flux_kind"] == "magnitude"
    assert np.allclose(out.flux, lc.flux / np.median(lc.flux), atol=2e-3)  # median-normalised


def test_counts_are_normalised(tmp_path, clean_lc):
    lc, _ = clean_lc
    p = tmp_path / "c.csv"
    with open(p, "w") as f:
        f.write("time,flux\n")
        for t, fl in zip(lc.time, lc.flux * 15000):
            f.write(f"{t:.6f},{fl:.4f}\n")
    out, prof = load_lightcurve(p)
    assert prof["flux_kind"] == "counts"
    assert abs(np.median(out.flux) - 1) < 1e-9
    assert prof.get("uncertainties_estimated")


def test_headerless_file_needs_mapping(tmp_path, clean_lc):
    lc, _ = clean_lc
    p = tmp_path / "n.txt"
    np.savetxt(p, np.c_[lc.time, lc.flux, lc.flux_err])
    prof = build_profile(read_table(p))
    assert prof["category"] == "unknown" and prof["needs_confirmation"]
    prof2 = build_profile(read_table(p), {"time": "col1", "flux": "col2", "flux_err": "col3"})
    assert prof2["category"] == "photometric_time_series"
    assert prof2["roles"]["time"]["source"] == "user"


def test_generic_names_only_flagged_for_confirmation(tmp_path, clean_lc):
    lc, _ = clean_lc
    p = write_csv(tmp_path / "g.csv", lc, header=("t", "f", "e"))
    prof = build_profile(read_table(p))
    assert prof["needs_confirmation"]
    assert any("generic column names" in i["text"] for i in prof["quality_issues"])


def test_radial_velocity_recognised_but_not_analysable(tmp_path):
    p = tmp_path / "rv.csv"
    with open(p, "w") as f:
        f.write("bjd,rv,rv_err\n")
        for i in range(40):
            f.write(f"{2458000 + i * 3.1},{10 * np.sin(i)},1.2\n")
    prof = build_profile(read_table(p))
    assert prof["category"] == "radial_velocity"
    assert prof["applicable_methods"][0]["status"] == "planned"
    assert "no analysis module is implemented" in " ".join(prof["limitations"])


def test_spectrum_recognised(tmp_path):
    p = tmp_path / "s.csv"
    with open(p, "w") as f:
        f.write("wavelength,flux\n")
        for i in range(200):
            f.write(f"{5000 + i * 0.5},{1 + 0.1 * np.sin(i / 5)}\n")
    assert build_profile(read_table(p))["category"] == "spectroscopy"


def test_ambiguous_time_wavelength_flux(tmp_path):
    p = tmp_path / "amb.csv"
    with open(p, "w") as f:
        f.write("time,wavelength,flux\n")
        for i in range(100):
            f.write(f"{i * 0.1},{5000 + i},{1 + 0.01 * np.sin(i)}\n")
    prof = build_profile(read_table(p))
    assert prof["category"] in ("photometric_time_series", "spectroscopy")
    assert any(a["category"] == "spectroscopy" or a["category"] == "photometric_time_series" for a in prof["alternatives"]) \
        or prof["ambiguous"] or prof["confidence"] < 0.8


def test_unrelated_table_is_unknown(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("name,colour\nfoo,red\nbar,blue\n")
    prof = build_profile(read_table(p))
    assert prof["category"] == "unknown" and prof["applicable_methods"] == []
    assert prof["limitations"]


def test_too_short_series_rejected_for_transit_search(tmp_path):
    p = tmp_path / "short.csv"
    with open(p, "w") as f:
        f.write("time,flux\n")
        for i in range(50):
            f.write(f"{i * 0.01},{1 + 1e-4 * np.sin(i)}\n")
    prof = build_profile(read_table(p))
    m = prof["applicable_methods"][0]
    assert m["status"] == "unsuitable" and "points" in m["reason"]


def test_empty_and_binary_and_corrupt_files(tmp_path):
    (tmp_path / "e.csv").write_text("")
    with pytest.raises(IngestError):
        read_table(tmp_path / "e.csv")
    (tmp_path / "b.csv").write_bytes(b"\x00\x01\x02\x03" * 100)
    with pytest.raises(IngestError):
        read_table(tmp_path / "b.csv")
    (tmp_path / "bad.fits").write_bytes(b"SIMPLE  =                    T" + b"junk" * 50)
    with pytest.raises(IngestError) as ei:
        read_table(tmp_path / "bad.fits")
    assert "FITS" in ei.value.message


def test_malformed_values_are_counted_not_fatal(tmp_path):
    p = tmp_path / "m.csv"
    lines = ["time,flux,flux_err"] + [f"{i * 0.02},{1 + 1e-4 * (i % 3)},1e-4" for i in range(400)]
    lines[10] = "abc,1.0,1e-4"
    lines[20] = "0.4,NaN,1e-4"
    p.write_text("\n".join(lines))
    prof = build_profile(read_table(p))
    assert prof["category"] == "photometric_time_series"
    assert prof["coverage"]["n_valid"] < prof["coverage"]["n_rows"]


def _tess_fits(path, lc, with_pdcsap=True, bad_quality_every=0):
    n = len(lc.time)
    q = np.zeros(n, dtype=int)
    if bad_quality_every:
        q[::bad_quality_every] = 1  # AttitudeTweak
    cols = [fits.Column(name="TIME", format="D", unit="BJD - 2457000, days", array=lc.time),
            fits.Column(name="SAP_FLUX", format="E", unit="e-/s", array=lc.flux * 1000 * 1.02)]
    if with_pdcsap:
        cols += [fits.Column(name="PDCSAP_FLUX", format="E", unit="e-/s", array=lc.flux * 1000),
                 fits.Column(name="PDCSAP_FLUX_ERR", format="E", unit="e-/s", array=lc.flux_err * 1000)]
    cols.append(fits.Column(name="QUALITY", format="J", array=q))
    h0 = fits.PrimaryHDU()
    h0.header["TELESCOP"], h0.header["OBJECT"], h0.header["SECTOR"] = "TESS", "TIC 1", 5
    h1 = fits.BinTableHDU.from_columns(cols, name="LIGHTCURVE")
    h1.header["BJDREFI"], h1.header["BJDREFF"], h1.header["TIMEUNIT"] = 2457000, 0.0, "d"
    fits.HDUList([h0, h1]).writeto(path)
    return path


def test_tess_fits_profile_and_load(tmp_path, clean_lc):
    lc, _ = clean_lc
    p = _tess_fits(tmp_path / "t.fits", lc)
    out, prof = load_lightcurve(p)
    assert prof["category"] == "photometric_time_series" and prof["confidence"] >= 0.9
    assert prof["roles"]["flux"]["column"] == "PDCSAP_FLUX"
    assert out.mission == "tess" and out.time_offset_jd == 2457000.0
    assert abs(np.median(out.flux) - 1) < 1e-6


def test_original_file_never_modified(tmp_path, clean_lc):
    lc, _ = clean_lc
    p = _tess_fits(tmp_path / "t.fits", lc)
    before = p.read_bytes()
    load_lightcurve(p)
    assert p.read_bytes() == before


def test_fits_image_only_is_image_category(tmp_path):
    p = tmp_path / "img.fits"
    fits.HDUList([fits.PrimaryHDU(np.random.default_rng(0).normal(size=(32, 32)))]).writeto(p)
    prof = build_profile(read_table(p))
    assert prof["category"] == "image"
    assert prof["applicable_methods"][0]["status"] == "planned"
