# Repeatable real-data demo

**Status: not run by the author.** The build sandbox had no access to NASA or MAST, so this demo (and the live archive
integration it relies on) is unverified. Treat the first run as the integration test.

Requires network access to `exoplanetarchive.ipac.caltech.edu` and `mast.stsci.edu`.

```bash
cd backend && pip install -r requirements.txt

# 1. Check each archive assumption separately (OK / FAIL per step, writes nothing to the app database)
python ../scripts/verify_archives.py "pi Men"

# 2. End-to-end: search → target detail → download one TESS SPOC light curve → profile → transit analysis → export
python ../scripts/demo_real_data.py "pi Men" [--sector N]
```

The demo target, pi Mensae, hosts a published transiting planet (pi Men c). The script writes `demo_output/analysis.json`,
`candidates.csv` and `report.html`, and prints the candidates with their labels, plus the published periods for comparison.
Expected outcome *if* the signal reaches the detection thresholds in a single sector: it is labelled as matching the published planet,
not as a new signal. If it does not, the run reports a weak/no signal; that is a legitimate result, not a failure of the integration.
The same flow is available in the web UI: *Explore* → search → import observation → analyse.

If a step fails, run with `VERBOSE=1 python ../scripts/verify_archives.py` and fix the corresponding client in `backend/app/archives/`.
