"""Check the live archive integrations from a machine with network access.

    cd backend && python ../scripts/verify_archives.py [TARGET]

The build sandbox could not reach the archives, so the clients were written against the published
documentation and tested with mocked responses. Run this once on your machine: each step prints
OK / FAIL with the reason, and nothing here writes to the app database.
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("EXPLORER_DATA_DIR", tempfile.mkdtemp(prefix="explorer-verify-"))

from app import db  # noqa: E402
from app.archives import exomast, mast, nasa  # noqa: E402
from app.services import targets  # noqa: E402

TARGET = sys.argv[1] if len(sys.argv) > 1 else "pi Men"
FAILS: list[str] = []


def step(name, fn):
    try:
        out = fn()
        print(f"OK    {name}: {out}")
        return out
    except Exception as e:  # report every failure and keep going
        FAILS.append(name)
        print(f"FAIL  {name}: {e.__class__.__name__}: {e}")
        if os.environ.get("VERBOSE"):
            traceback.print_exc()
        return None


db.init_db()
step("NASA TAP reachable (pscomppars)", lambda: nasa.tap_query("select top 1 pl_name, hostname from pscomppars")[0])
step("NASA TOI table columns (tid, toi, tfopwg_disp)", lambda: nasa.tap_query("select top 1 tid, toi, tfopwg_disp from toi")[0])
step("NASA KOI table columns (kepid, kepoi_name)", lambda: nasa.tap_query("select top 1 kepid, kepoi_name, koi_disposition from cumulative")[0])
res = step(f"Target search '{TARGET}'", lambda: [(r["host"], r["kind"]) for r in targets.search(TARGET)["results"]])
step("MAST Mast.Name.Lookup", lambda: mast.name_lookup(TARGET))
step("Exo.MAST identifiers", lambda: (exomast.identifiers("WASP-18 b") or {}).get("aliases", [])[:5])
if res:
    key = targets.search(TARGET)["results"][0]["key"]
    det = step("Target detail", lambda: {"planets": len(targets.detail(key)["published_planets"]),
                                         "observations": targets.detail(key)["n_observations"]})
    d = targets.detail(key)
    sup = [o for g in d["observations"].values() for o in g if o["analysis_supported"]]
    if sup:
        prods = step("MAST product listing", lambda: mast.list_light_curve_products(sup[0]["obsid"])["products"][:2])
        print("      (download is exercised by the demo script: scripts/demo_real_data.py)")
print("\nAll checks passed." if not FAILS else f"\n{len(FAILS)} check(s) failed: {FAILS}")
sys.exit(1 if FAILS else 0)
