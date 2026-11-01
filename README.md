# Yatra - Exoplanet Explorer
> "Yatra" means "Voyage" in Sanskrit.

A web application for exploring exoplanet data and analysing light curves. Two entry points share one pipeline
(ingest → profile → analysis → visualisation → report):

* **Upload data** – CSV / TXT / FITS. The app profiles the file from evidence (columns, units, cadence, coverage, quality issues),
  tells you what it thinks the data are and how confident it is, lets you correct the column mapping, and offers only the
  analysis methods that apply.
* **Explore a target** – search a star or planet; the target page shows the host star, published planets (NASA Exoplanet
  Archive) and observations (MAST), each with its source and retrieval time. A supported light curve can be imported and
  analysed exactly like an upload.

Method selection is rule-based (a registry of modules with prerequisites). No language model chooses or runs an analysis.

> **Verification status, read this first.** The backend, analysis engine, UI and tests were built and run in a sandbox with
> **no access to NASA/MAST**. The archive clients were written from published documentation and are tested only against
> mocked responses. They have **never been run against the live services**. Run `scripts/verify_archives.py` once
> (see below) before relying on Explore. See [docs/TESTING.md](docs/TESTING.md) for exactly what was and was not measured.

## Implemented vs planned

| Capability | Status |
|---|---|
| Upload (CSV/TXT/FITS), dataset profiling, manual column mapping | Implemented, tested |
| Transit photometry: cleaning, detrending, BLS search, vetting, batman fit, uncertainties | Implemented, tested on synthetic data |
| Background jobs, saved analyses, JSON / CSV / HTML exports with provenance | Implemented, tested |
| NASA Exoplanet Archive / MAST / Exo.MAST clients, target pages | Implemented, **mock-tested only** |
| Radial-velocity periodogram | **Planned** (shown as planned in the UI, not runnable) |
| Transmission spectroscopy, direct imaging, astrometric orbits | **Planned** |
| Accounts, multi-user isolation, public hosting hardening | Not implemented |

## Scientific integrity rules

* A signal found in your data is never called "confirmed". Result categories: `matches_published_planet`,
  `matches_known_candidate`, `new_unvalidated_signal`, `likely_variability`, `weak_signal`.
* Catalogue comparison uses only the server-side archive lookup; clients cannot inject it.
* No planet radius is reported without a stellar radius (you can supply one).
* Original files are never modified; uploaded content is parsed as data and never executed.
* Every analysis stores dataset hash, schema/mapping, parameters, preprocessing, library versions and warnings.

## Layout

```
backend/    FastAPI app (app/), tests (tests/), requirements.txt, Dockerfile
frontend/   Next.js + TypeScript + Plotly
scripts/    verify_archives.py, demo_real_data.py
docs/       ARCHITECTURE.md, TESTING.md, DEMO.md
.env.example
```

## Local setup

Requires Python 3.11+ and Node 18+.

```bash
# optional: copy .env.example to backend/.env (and frontend/.env.local); every setting has a default

# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                     # http://localhost:3000, proxies /api to the backend
```

### Windows (PowerShell)

Quick way: double-click `setup.bat` once (installs everything), then `start.bat` (launches both servers and opens the browser).
These scripts were written without access to Windows and are untested. The manual steps below do the same thing.

Install Python 3.11, 3.12 or 3.13 (not 3.14: `batman-package` has no prebuilt Windows wheel for it, which makes pip try to compile it and fail without C++ build tools) (tick "Add to PATH") and Node 18+ LTS first. Unzip the project, then use two PowerShell windows:

```powershell
# window 1: backend
cd exoplanet-explorer\backend
py -m venv .venv
.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# window 2: frontend
cd exoplanet-explorer\frontend
npm install
npm run dev                          # open http://localhost:3000
```

Run tests: `cd backend; python -m pytest -o addopts=""`. Windows has not been tested by the author (built on Linux);
analysis workers use the `spawn` start method, which is the Windows default, so no change should be needed. If
`batman-package` fails to build, install "Microsoft C++ Build Tools" or use WSL2 (`wsl --install`, then follow the Linux steps).

Production build: `npm run build && npm start`. Configuration is by environment variables (prefix `EXPLORER_`, see
`.env.example`): data directory, upload size/TTL, worker count, offline mode, archive URLs, contact e-mail for archive
requests. No secrets are required or stored in the repository.

Set `EXPLORER_OFFLINE=true` to forbid all outbound archive requests (uploads and analysis still work).

## Using it

**Upload.** *Upload Data* → drop a file → review the profile (category, confidence, detected columns and units, issues,
coverage, applicable methods, limitations) → fix the mapping if needed → choose *Transit search*, optionally enter stellar
radius/Teff → run. Results appear under *My Analyses* with plots, candidate table, vetting checks and exports.

**Search.** *Explore* → type a name (e.g. `pi Men`, `TOI-270`, `WASP-18 b`) → the target page lists published planets and
observations → import a supported TESS/Kepler light-curve product → analyse it. Published planets found in the data are
labelled as matching the archive, never as new.

## Tests

```bash
cd backend && python -m pytest -o addopts=""          # ~5 min, offline
python -m pytest -m live                              # opt-in, needs network
```

Results and measured performance: [docs/TESTING.md](docs/TESTING.md). Real-data demo: [docs/DEMO.md](docs/DEMO.md).

## Deployment

* **Frontend**: any Node host (or a platform that runs Next.js). It proxies `/api/*` to the backend; set the backend URL with the
  `API_URL` environment variable (default `http://localhost:8000`, see `frontend/next.config.mjs`).
* **Backend**: needs a host that allows long-lived processes and a persistent volume for `EXPLORER_DATA_DIR` (SQLite + uploads).
  `backend/Dockerfile` builds an image: `docker build -t explorer-api backend && docker run -p 8000:8000 -v explorer-data:/data explorer-api`.
  Do not use a short-timeout serverless runtime: analyses run in worker processes for tens of seconds to minutes.
* Put TLS and authentication in front of the API before exposing it publicly; the app itself has no user accounts.
  Keep `EXPLORER_MAX_UPLOAD_MB` and `EXPLORER_MAX_WORKERS` modest.
* **No deployment was performed or verified for this project.** The Dockerfile has not been built here.

## Known limitations

* Archive integrations unverified against live services (see above).
* Transit search is calibrated and benchmarked on synthetic data with white noise plus simple variability; real data have
  correlated noise, so false-alarm rates on real light curves will differ.
* Shallow signals (depth ≲ 300 ppm at 500 ppm per-point noise over 27 d) are generally missed.
* Circular orbits and fixed quadratic limb darkening in the fit; single-sector analysis only.
* Single-user design, SQLite storage.
## Local estimated parameters

The app can fill a missing planet property with a clearly marked **ML estimate**. Archive measurements are never replaced, and an estimate is not evidence that a planet is confirmed or transiting. The portable model is committed at `backend/models/planet_property_model.json`, so normal installs infer only and never retrain.

To deliberately refresh it on your own machine (with `numpy` installed), run:

```bash
cd backend
python ../scripts/train_planet_property_model.py
```

This downloads the NASA Exoplanet Archive composite table once, trains small ridge-regression models locally, and rewrites the versioned JSON artifact. Review and commit that file if you want the new model to ship with the project.

