"""Exports: machine-readable JSON, candidate CSV and a self-contained HTML report."""
from __future__ import annotations

import base64
import csv
import html
import io
import json
from typing import Any

import numpy as np

KIND_LABEL = {
    "matches_published_planet": "Consistent with a published planet",
    "matches_known_candidate": "Consistent with a catalogued candidate",
    "new_unvalidated_signal": "New unvalidated signal (candidate)",
    "likely_variability": "Probable variability / systematic",
    "weak_signal": "Weak peak (not a detection)",
}


def candidates_csv(analysis: dict[str, Any]) -> str:
    cols = ["rank", "classification", "period_d", "t0_rel_d", "t0_jd", "duration_h", "depth_ppm", "depth_snr", "sde",
            "n_transits", "rp_rs", "rp_rs_err", "a_rs", "b", "planet_radius_earth", "vetting_fail", "vetting_warn"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for c in analysis["result"]["candidates"]:
        fit = (c.get("fit") or {})
        pr = fit.get("params", {})
        rad = (fit.get("derived") or {}).get("planet_radius_earth")
        w.writerow([
            c["rank"], c["kind"], c["period"], c["t0"], c.get("t0_absolute_jd"), c["duration"] * 24, c["depth"] * 1e6,
            c["depth_snr"], c["sde"], c["n_transits_observed"],
            pr.get("rp_rs", {}).get("value"), pr.get("rp_rs", {}).get("err"),
            pr.get("a_rs", {}).get("value"), pr.get("b", {}).get("value"),
            rad["value"] if rad else None, c["vetting"]["n_fail"], c["vetting"]["n_warn"]])
    return buf.getvalue()


def export_json(analysis: dict[str, Any]) -> str:
    return json.dumps(analysis, indent=2, default=float)


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _plots(res: dict[str, Any]) -> dict[str, Any]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    out: dict[str, Any] = {}
    s = res["series"]
    fig, ax = plt.subplots(2, 1, figsize=(8, 4.4), sharex=True)
    ax[0].plot(s["raw"]["time"], s["raw"]["flux"], ",", color="#555")
    if s["trend"]["time"]:
        ax[0].plot(s["trend"]["time"], s["trend"]["flux"], "-", color="#c0392b", lw=0.8, label="trend")
        ax[0].legend(loc="upper right", frameon=False)
    ax[0].set_ylabel("Normalised flux (raw)")
    ax[1].plot(s["flattened"]["time"], s["flattened"]["flux"], ",", color="#222")
    for c in res["candidates"]:
        if c["below_threshold"]:
            continue
        P, t0 = c["period"], c["t0"]
        t = np.array(s["flattened"]["time"])
        if len(t):
            n = np.arange(np.floor((t.min() - t0) / P), np.ceil((t.max() - t0) / P) + 1)
            for tt in t0 + n * P:
                if t.min() <= tt <= t.max():
                    ax[1].axvline(tt, color="#2a6fdb", alpha=0.25, lw=0.8)
    ax[1].set_ylabel("Flattened flux")
    ax[1].set_xlabel(f"Time ({s['time_format']}, days)")
    out["lc"] = _png(fig)
    out["periodogram"] = []
    for sp in res["periodograms"]:
        fig, a = plt.subplots(figsize=(8, 2.4))
        a.plot(sp["period"], sp["sde_flattened"], lw=0.7, color="#222")
        a.set_xscale("log")
        a.set_xlabel("Period (d)")
        a.set_ylabel("BLS power (flattened)")
        a.set_title(f"Search pass {sp['rank']}", fontsize=9, loc="left")
        out["periodogram"].append(_png(fig))
    out["folds"] = []
    for c in res["candidates"]:
        fig, a = plt.subplots(figsize=(5.2, 3))
        fd = c["folded"]
        a.errorbar(np.array(fd["phase"]) * 24, fd["flux"], fd["err"], fmt="o", ms=2.5, color="#222", lw=0.6)
        if c.get("model"):
            a.plot(np.array(c["model"]["phase"]) * 24, c["model"]["flux"], color="#c0392b", lw=1.4)
        a.set_xlabel("Hours from mid-transit")
        a.set_ylabel("Flux")
        out["folds"].append(_png(fig))
    return out


def _fmt(v, nd=5):
    return "—" if v is None else (f"{v:.{nd}g}" if isinstance(v, float) else html.escape(str(v)))


def report_html(analysis: dict[str, Any], app_name: str = "Exoplanet Explorer") -> str:
    res = analysis["result"]
    prov = res["provenance"]
    plots = _plots(res)
    e = html.escape
    rows = []
    for c, img in zip(res["candidates"], plots["folds"]):
        fit = c.get("fit") or {}
        pr = fit.get("params", {})
        derived = fit.get("derived") or {}
        rad = derived.get("planet_radius_earth")
        checks = "".join(
            f"<li class='{ch['status']}'><b>{e(ch['id'])}</b> [{ch['status']}] {e(ch['detail'])}</li>" for ch in c["vetting"]["checks"])
        ptab = "".join(
            f"<tr><td>{n}</td><td>{_fmt(p['value'], 7)}</td><td>{_fmt(p['err'], 3)}</td><td>{e(p['method'])}</td></tr>"
            for n, p in pr.items())
        rows.append(f"""
<section class="cand"><h3>Signal {c['rank']}: {e(KIND_LABEL.get(c['kind'], c['kind']))}</h3>
<p class="status">{e(c['status_text'])}</p>
<table><tr><th>Period (d)</th><th>Duration (h)</th><th>Depth (ppm)</th><th>S/N</th><th>SDE</th><th>Transits</th></tr>
<tr><td>{c['period']:.5f}</td><td>{c['duration'] * 24:.2f}</td><td>{c['depth'] * 1e6:.0f}</td><td>{c['depth_snr']:.1f}</td>
<td>{c['sde']:.1f}</td><td>{c['n_transits_observed']}</td></tr></table>
<img src="{img}" alt="Folded light curve for signal {c['rank']}" width="420">
{('<h4>Model fit</h4><table><tr><th>Parameter</th><th>Value</th><th>±</th><th>Uncertainty method</th></tr>' + ptab + '</table>') if pr else '<p>No model fit for this signal.</p>'}
{('<p>Planet radius: %s R⊕ (assuming R★=%s R☉)</p>' % (_fmt(rad['value'], 4), _fmt(rad['stellar_radius_rsun'], 4))) if rad else '<p>Planet radius not computed: no stellar radius supplied.</p>'}
{''.join('<p class="flag">' + e(x) + '</p>' for x in fit.get('flags', []))}
<h4>Vetting checks</h4><ul>{checks}</ul></section>""")
    pre = prov.get("preprocessing_pass2") or prov.get("preprocessing_pass1")
    params = json.dumps(prov["parameters"], indent=2, default=str)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(app_name)} analysis report</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#111}}
table{{border-collapse:collapse;margin:.5rem 0}}td,th{{border:1px solid #ccc;padding:3px 8px;text-align:left}}
.cand{{border-top:2px solid #111;margin-top:2rem}}.fail{{color:#a02020}}.warn{{color:#8a5a00}}.pass{{color:#256029}}
.status{{font-weight:600}}.flag{{background:#f6f1e0;padding:4px 8px}}pre{{background:#f5f5f5;padding:8px;overflow:auto}}
.banner{{border:1px solid #111;padding:8px 12px;margin:1rem 0}}img{{max-width:100%}}</style></head><body>
<h1>{e(app_name)}: transit analysis report</h1>
<div class="banner"><b>Interpretation notice.</b> Signals below are algorithmic candidates. None is a confirmed or validated
exoplanet; confirmation requires follow-up (e.g. centroid/difference-image tests, ground-based photometry, spectroscopy) that
this tool does not perform.</div>
<h2>Summary</h2><p>{e(res['summary'])}</p>
{''.join('<p class="flag">' + e(w) + '</p>' for w in res['warnings'])}
<h2>Input</h2><p>Dataset: {e(str(prov['dataset']['name']))} ({e(prov['dataset']['source'])}), sha256 <code>{e(str(prov['dataset']['sha256']))}</code></p>
<p>Detected schema: category {e(prov['input_schema']['category'])} (confidence {prov['input_schema']['confidence']}), flux convention {e(str(prov['input_schema']['flux_kind']))}.</p>
<h2>Light curve</h2><img src="{plots['lc']}" alt="Raw and flattened light curve">
<h2>Preprocessing</h2><pre>{e(json.dumps(pre, indent=2, default=str))}</pre>
<h2>Period search</h2>{''.join('<img src="' + p + '" alt="BLS periodogram">' for p in plots['periodogram'])}
<h2>Signals</h2>{''.join(rows)}
<h2>Reproducibility</h2><p>Analysis id <code>{e(prov['analysis_id'])}</code>; module {e(prov['module'])}.</p>
<h4>Parameters</h4><pre>{e(params)}</pre><h4>Library versions</h4><pre>{e(json.dumps(prov['versions'], indent=2))}</pre>
<p>{e(prov.get('library_note', ''))}</p></body></html>"""
