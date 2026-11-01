"""Repeatable demo on a real, public dataset: a TESS SPOC light curve from MAST.

    cd backend && python ../scripts/demo_real_data.py ["pi Men"] [--sector N]

Steps (all through the same code the web app uses): resolve the target → list TESS SPOC light-curve
observations → download one product (limited to EXPLORER_MAX_PRODUCT_MB) → profile → transit analysis →
write JSON/CSV/HTML into ./demo_output. The default target (pi Mensae) hosts a published transiting planet
(pi Men c), so the run shows how a catalogued planet is recovered and labelled. Whether a single sector reaches the
detection thresholds depends on the planet's depth, and this script has not been run by its author (no archive
access in the build sandbox): treat its first run as a verification of the live integration.
Requires network access to NASA Exoplanet Archive and MAST. Nothing is simulated.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("EXPLORER_DATA_DIR", tempfile.mkdtemp(prefix="explorer-demo-"))

from app import db  # noqa: E402
from app.archives import mast  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.services import datasets, jobs, report, targets  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("target", nargs="?", default="pi Men")
ap.add_argument("--sector", type=int, default=None, help="TESS sector (default: the first supported observation)")
ap.add_argument("--out", default="demo_output")
a = ap.parse_args()

db.init_db()
print(f"1. Searching for '{a.target}' …")
hits = targets.search(a.target)
for e in hits["errors"]:
    sys.exit(f"Archive error: {e}")
if not hits["results"]:
    sys.exit("No match found.")
key = hits["results"][0]["key"]
det = targets.detail(key)
print(f"   {det['label']}: {len(det['published_planets'])} published planet(s), {det['n_observations']} observation(s)")
for e in det["errors"]:
    print("   archive warning:", e)
obs = [o for g in det["observations"].values() for o in g if o["analysis_supported"] and o["mission"] == "TESS"]
if a.sector:
    obs = [o for o in obs if o["sequence"] == a.sector]
if not obs:
    sys.exit("No supported TESS SPOC observation for this target/sector.")
o = obs[0]
print(f"2. Using TESS sector {o['sequence']} (obsid {o['obsid']}, {o['start_date']} → {o['end_date']})")
prods = mast.list_light_curve_products(o["obsid"])["products"]
if not prods:
    sys.exit("No light-curve product listed for that observation.")
p = prods[0]
print(f"3. Downloading {p['filename']} ({(p['size_bytes'] or 0) / 1e6:.1f} MB) …")
path = mast.download_product(p["uri"], p["size_bytes"], get_settings().data_dir / "archive_cache")
ds = datasets.import_archive_file(path, p["filename"], {"archive": "MAST", "obsid": o["obsid"], "product_uri": p["uri"],
                                                     "filename": p["filename"], "target": det["label"], "mission": "TESS"})
prof = ds["profile"]
print(f"4. Profile: {prof['category_label']} ({prof['confidence']:.0%}); flux column {prof['roles']['flux']['column']}")

star = (det["star"] or {})
params = {"star": {"teff": (star.get("teff") or {}).get("value"), "radius_rsun": (star.get("radius") or {}).get("value"),
                   "radius_err_rsun": (star.get("radius") or {}).get("err_plus")},
          "known_planets": targets.known_planets_for_analysis(det)}
print("5. Running the transit analysis (this takes a minute or two) …")
aid = jobs.create(ds["id"], "transit_bls", params)
jobs.submit(aid, inline=True)
an = jobs.get(aid)
if an["status"] != "succeeded":
    sys.exit(f"Analysis failed: {an['error']}")
res = an["result"]
print("   " + res["summary"])
for c in res["candidates"]:
    print(f"   #{c['rank']} P={c['period']:.5f} d depth={c['depth'] * 1e6:.0f} ppm SDE={c['sde']:.1f} → {c['status_text']}")
print("   published periods:", [(k["name"], round(k["period"], 5)) for k in params["known_planets"]])

out = Path(a.out)
out.mkdir(exist_ok=True)
(out / "analysis.json").write_text(report.export_json(an))
(out / "candidates.csv").write_text(report.candidates_csv(an))
(out / "report.html").write_text(report.report_html(an, get_settings().app_name))
print(f"6. Wrote {out}/analysis.json, candidates.csv, report.html")
