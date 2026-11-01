# Testing, measured performance and limitations

Everything below was measured in the build sandbox on **synthetic** light curves (generator: `backend/app/synthetic.py`) and
with **mocked** archive responses. Nothing here was measured against real archive data or live NASA/MAST services.

## Automated tests

`cd backend && python -m pytest -o addopts=""` → **69 passed, 1 deselected (the opt-in `live` test), ~297 s**. Offline; no network.

| File | Covers |
|---|---|
| `test_ingest.py` | CSV/TXT/FITS reading, headerless and ambiguous files, unit/time inference, profiling categories, size/row limits, mapping override, original file untouched |
| `test_transit_recovery.py` | Injected-transit recovery (period, depth, radius, two planets), noise-only rejection (fixed seeds), variability labelling |
| `test_transit_vetting.py` | Odd/even, secondary eclipse, single-event, alias, catalogue matching, no "confirmed" label, no radius without stellar radius |
| `test_archives.py` | NASA/MAST/Exo.MAST clients against `httpx.MockTransport` and a stubbed astroquery seam; caching and provenance; URI/size guards; offline mode; ADQL escaping |
| `test_api.py` | Upload → profile → analysis → export through the HTTP API; clients cannot supply catalogue data |

A browser end-to-end run (Playwright against the built frontend and live backend, with an uploaded synthetic file) passed during
development. That script lives in the build scratch area, not in the repository.

## False-alarm measurements (noise only, no transit)

| Data | Result |
|---|---|
| White noise, 10-min cadence, 33 light curves | SDE ≥ 7: 11/33; SDE ≥ 8.5: 2/33; **joint criterion (SDE ≥ 8.5 and box S/N ≥ 7.1): 0/33** |
| White noise, 2-min cadence, 24 light curves | SDE ≥ 7: 5/24; maximum SDE 7.94 |
| Noise + 0.4 % sinusoidal variability, 14 light curves | 14/14 labelled `likely_variability`, none as planet candidates |

The detection thresholds were chosen from these runs, so they are calibrated on the same kind of data they were measured on.
Sample sizes are small (≈30), so "0/33" bounds the false-alarm rate at roughly under 10 % per light curve at 95 % confidence, not at zero.
Real light curves have correlated noise and will behave differently.

## Injection–recovery (30 trials)

One transiting planet injected per trial: log-uniform period 1.5–12 d, 27 d baseline, 10-min cadence, 500 ppm per-point noise,
random depth from five values, `max_candidates=1`. "Recovered" = detected as a signal with fitted period within 1 % of truth.
Script: `inject.py` (build scratch area); raw results were not stored in the repository.

| Rp/Rs | Depth (ppm) | Trials | Detected | Recovered | Median SDE | Median \|ΔP\|/P | Rp/Rs bias (median, range) |
|---|---|---|---|---|---|---|---|
| 0.012 | 144 | 6 | 0 | 0 | 6.5 | – | – |
| 0.018 | 324 | 4 | 1 | 1 | 8.1 | 0.012 % | +9 % (one case) |
| 0.025 | 625 | 8 | 8 | 7 | 15.7 | 0.027 % | −3 % (−6 to +2 %) |
| 0.035 | 1225 | 8 | 8 | 8 | 20.5 | 0.019 % | +2 % (−3 to +16 %) |
| 0.050 | 2500 | 4 | 4 | 4 | 19.7 | 0.009 % | −0.4 % (−1 to +6 %) |

* Overall: 20/30 recovered. Missed cases: 9 weak signals (all ≤ 324 ppm, including every 144 ppm planet) and
  one 625 ppm case where the search locked onto a period alias (reported as a signal, wrong period).
* Fit-uncertainty calibration: the true period fell within 2σ in 17/20 recovered trials. Small sample, but the quoted period
  errors look somewhat optimistic; treat them as lower bounds.
* False positives in this experiment: none (every trial contained a real planet; false alarms are in the table above).
* Runtime: median 17 s per 27-day, 10-min-cadence analysis (range 7–19 s); 2-min cadence ≈ 30–50 s. Single process, this sandbox.

## Known limitations

* Archive clients never run against live services; TAP column names for the TOI/KOI tables and the Exo.MAST response shapes are
  unverified. `scripts/verify_archives.py` reports which assumptions fail.
* Synthetic data only: white noise, simple sinusoidal variability, circular orbits, no stellar flares, no systematics.
* Shallow transits (< ~300 ppm at this noise) are not recovered; period aliases (P/2, 2P) can occur.
* Fit: circular orbit, fixed limb darkening; Rp/Rs outliers up to +16 % occurred.
* FITS reading is tested with synthetic FITS only, not real SPOC/Kepler files.
* No load/concurrency testing; no deployment was built or run.
