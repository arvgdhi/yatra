# Architecture

```
 Browser ── Next.js (TypeScript, Plotly) ──/api proxy──▶ FastAPI ──▶ SQLite (datasets, analyses, cache, recent targets)
                                                            │
        both entry points converge here ───────────────────┤
   upload ─▶ services/datasets ─┐                          │
   target ─▶ archives/* ─▶ import product ─┘               ▼
                                          ingest (reader → profiler → loader)  ─▶ LightCurve
                                                            │
                                         analysis/registry (rule-based module selection)
                                                            │
                                    services/jobs ─▶ worker process ─▶ analysis/transit/{preprocess,search,vetting,fit,pipeline}
                                                            │
                                                  services/report (JSON · CSV · HTML)
```

## Repository was empty

There was no existing pipeline or application to preserve, so the project was scaffolded from the default architecture in the
brief (Next.js + FastAPI + SQLite). One deviation: MAST observation search, product listing and download use `astroquery.mast`
instead of hand-written HTTP calls, because the product and download endpoints could not be confirmed from documentation
reachable at build time. Name resolution uses the documented `Mast.Name.Lookup` service directly.

## One architecture, two entry points

Uploading a file and importing an archive product both end in `services.datasets` (register file → profile → store) and share
`ingest.loader.load_lightcurve`, the analysis registry, the job runner and the exporters. An archive dataset differs only in its
recorded provenance (MAST obsid, product URI, retrieval time).

## Backend modules (`backend/app`)

| Module | Responsibility |
|---|---|
| `ingest/reader.py` | Safe parsing of delimited text and FITS into a `RawTable`; never executes content; size/row limits. |
| `ingest/columns.py` | Column alias tables, unit and time-convention inference. |
| `ingest/profiler.py` | Evidence-based classification (photometry, RV, spectroscopy, image, astrometry, unknown), confidence, ambiguity, coverage, quality issues, applicable methods, limitations. |
| `ingest/loader.py` | Profiled table → `core.lightcurve.LightCurve` (unit/flux/magnitude conversion; originals untouched). |
| `archives/nasa.py` | NASA Exoplanet Archive TAP client (`pscomppars`, `toi`, `cumulative`) using documented column names only. |
| `archives/mast.py` | MAST name lookup and astroquery-backed observations/products/download with URI and size guards. |
| `archives/exomast.py` | Exo.MAST identifier/autocomplete (defensive parsing; schemas are undocumented). |
| `archives/base.py` | HTTP client, SQLite cache with provenance (source, query, retrieved_at, from_cache), `ArchiveError`. |
| `analysis/registry.py` | Module registry: input schema, prerequisites, parameters, outputs, limitations, validation tests; rule-based selection. |
| `analysis/transit/*` | Preprocessing, BLS search, vetting, batman fit, orchestration. |
| `services/jobs.py` | Analyses run in separate worker processes; progress/status/result stored in SQLite; stale jobs failed on restart. |
| `services/report.py` | JSON, CSV and self-contained HTML report with figures. |
| `services/targets.py` | Target search/detail across archives with partial-result handling. |

## Scientific integrity rules enforced in code

* Result categories are `matches_published_planet`, `matches_known_candidate`, `new_unvalidated_signal`, `likely_variability`,
  `weak_signal`. There is no "confirmed" category. Catalogue comparison data come only from the server's archive lookup; a client
  cannot supply them (tested).
* No planet radius without a stellar radius.
* The original observation file is never modified (tested); processing works on copies.
* Every result stores: dataset sha256 and provenance, detected schema and any manual mapping, all parameters, preprocessing record,
  dependency versions, warnings.

## Transit workflow details and design decisions

1. **Cleaning**: mission quality bitmasks (default/hard/hardest/none; bit definitions mirror Lightkurve's), non-finite removal, high
   outlier clipping, and clipping of *isolated* low points only.
2. **Detrending**: time-windowed running median (0.75 d default). Measured on a synthetic 0.4 % sinusoid, the filter's bias rises to ~900 ppm
   at data edges and decays to the ~110 ppm interior level by half a window, so points within half a window of every segment edge are
   trimmed. A second pass masks detected transits before re-estimating the trend.
3. **Search**: Astropy BLS in period segments, each with a physically limited duration grid
   (`min(ceiling, 2.5·0.0753·P^(1/3) d, P/3)`; also ≤ window/3). Without these limits BLS reports near-full-orbit "transits".
   Fine-cadence data are binned to 10 min for the search only; fitting uses full data.
4. **Detection criteria**: SDE ≥ 8.5 **and** box-depth S/N ≥ 7.1 (see `TESTING.md` for the noise-only measurements behind this).
5. **Vetting**: significance, S/N, transit count, coverage, single-event dominance, odd/even, secondary eclipse, sinusoid alternative,
   depth and duration plausibility, period aliases, cadence. A sinusoid-preferred signal is labelled `likely_variability`.
6. **Fit**: batman, free T0/P/Rp/Rs/a/Rs/b, fixed quadratic limb darkening, circular orbit. Errors from the Jacobian, widened by a
   profile over b; errors that are invalid (parameter at a bound) are reported as unconstrained instead of a number. Optional emcee.
   Other detected signals' transits are masked out of each fit.

## Persistence and cleanup

SQLite tables: `datasets`, `analyses`, `cache`, `recent_targets`. Uploaded files live in `data/uploads/<random id>/`, are size-limited
while streaming, and are deleted after `EXPLORER_UPLOAD_TTL_HOURS` (checked at startup). Results keep their own JSON.

## Deployment shape

The frontend can run on any Node host (or a static/serverless host that proxies `/api`). The backend must run on a host that allows
long-lived processes (analysis workers are spawned processes); do not deploy it to a short-timeout serverless runtime. See the README.
