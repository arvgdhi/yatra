import os
import tempfile
from pathlib import Path

# Isolated data dir must be set before the app settings are first read.
_TMP = tempfile.mkdtemp(prefix="explorer-tests-")
os.environ["EXPLORER_DATA_DIR"] = _TMP
os.environ["EXPLORER_OFFLINE"] = "false"

import httpx
import numpy as np
import pytest

from app import db
from app.archives import base
from app.config import get_settings
from app.synthetic import make_lightcurve


@pytest.fixture(autouse=True, scope="session")
def _init():
    get_settings().ensure_dirs()
    db.init_db()


@pytest.fixture(autouse=True)
def _no_real_network():
    """Any archive HTTP call in a test that did not install its own transport fails loudly."""
    def refuse(request: httpx.Request):
        raise AssertionError(f"Unexpected real network request in test: {request.url}")
    base.set_transport(httpx.MockTransport(refuse))
    with db.connect() as c:
        c.execute("DELETE FROM cache")
    yield
    base.set_transport(None)


@pytest.fixture
def tmpdir_path(tmp_path: Path) -> Path:
    return tmp_path


def write_csv(path: Path, lc, header=("time", "flux", "flux_err"), time_scale=1.0, time_shift=0.0):
    with open(path, "w") as f:
        f.write(",".join(header) + "\n")
        for t, fl, e in zip(lc.time, lc.flux, lc.flux_err):
            f.write(f"{t * time_scale + time_shift:.6f},{fl:.7f},{e:.7f}\n")
    return path


@pytest.fixture(scope="session")
def clean_lc():
    return make_lightcurve(period=3.2, rp=0.05, noise_ppm=500, seed=1, baseline=20)
