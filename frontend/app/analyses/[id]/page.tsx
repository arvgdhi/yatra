"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Plot, { useColors } from "@/components/Plot";
import PlanetWireframe from "@/components/PlanetWireframe";
import { ApiError, fmt, get, when } from "@/lib/api";
import type { Analysis, Candidate } from "@/lib/types";

const KIND: Record<string, { label: string; tone: string }> = {
  matches_published_planet: { label: "Matches a published planet", tone: "strong" },
  matches_known_candidate: { label: "Matches a catalogued candidate", tone: "strong" },
  new_unvalidated_signal: { label: "New unvalidated signal", tone: "warn" },
  likely_variability: { label: "Probable variability / systematic", tone: "fail" },
  weak_signal: { label: "Weak peak, not a detection", tone: "" },
};
const TABS = ["Light curve", "Periodogram", "Candidates", "Data & provenance", "Downloads"] as const;

export default function Workspace() {
  const { id } = useParams<{ id: string }>();
  const [a, setA] = useState<Analysis | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Candidates");

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const r = await get<Analysis>(`/api/analyses/${id}`);
        if (stop) return;
        setA(r);
        if (r.status === "queued" || r.status === "running") timer = setTimeout(tick, 1500);
      } catch (e) {
        if (!stop) setErr(e instanceof ApiError ? e.message : "Could not load analysis");
      }
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [id]);

  if (err) return <div className="notice error" role="alert">{err}</div>;
  if (!a) return <p role="status">Loading analysis…</p>;

  return (
    <div>
      <p className="small muted"><Link href="/analyses">My Analyses</Link> / {a.id}</p>
      <h1>Transit analysis</h1>
      <p className="small muted">
        Dataset <Link href={`/datasets/${a.dataset_id}`}>{a.dataset_id}</Link> · started {when(a.created_at)}
        {a.finished_at ? ` · finished ${when(a.finished_at)}` : ""}
      </p>

      {(a.status === "queued" || a.status === "running") && (
        <div className="card" role="status" aria-live="polite">
          <b>{a.status === "queued" ? "Queued" : "Running"}</b>: {a.stage}
          <div className="progress" style={{ marginTop: 8 }} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(a.progress * 100)}>
            <div style={{ width: `${Math.round(a.progress * 100)}%` }} />
          </div>
          <p className="small muted" style={{ marginBottom: 0 }}>Long searches run in a separate worker process; you can leave this page and return.</p>
        </div>
      )}
      {a.status === "failed" && (
        <div className="notice error" role="alert">
          <b>The analysis could not be completed.</b>
          <div>{a.error}</div>
          <div className="small">Check the dataset profile and parameters, then run it again from the <Link href={`/datasets/${a.dataset_id}`}>dataset page</Link>.</div>
        </div>
      )}
      {a.status === "succeeded" && a.result && <Results a={a} tab={tab} setTab={setTab} />}
    </div>
  );
}

function Results({ a, tab, setTab }: { a: Analysis; tab: string; setTab: (t: any) => void }) {
  const r = a.result!;
  const sig = r.candidates.filter((c) => KIND[c.kind] && !["weak_signal", "likely_variability"].includes(c.kind));
  return (
    <>
      <div className={`notice ${sig.length ? "ok" : "warn"}`}>
        <b>{r.summary}</b>
        <div className="small">Signals are candidates produced by an algorithm. None is a confirmed or validated planet.</div>
      </div>
      {r.warnings.map((w, i) => <div className="notice warn" key={i}>{w}</div>)}
      <div className="tabs" role="tablist" aria-label="Analysis views">
        {TABS.map((t) => <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>{t}</button>)}
      </div>
      {tab === "Light curve" && <LightCurve a={a} />}
      {tab === "Periodogram" && <Periodogram a={a} />}
      {tab === "Candidates" && <Candidates a={a} />}
      {tab === "Data & provenance" && <Provenance a={a} />}
      {tab === "Downloads" && <Downloads a={a} />}
    </>
  );
}

function LightCurve({ a }: { a: Analysis }) {
  const r = a.result!;
  const c = useColors();
  const [showTrend, setShowTrend] = useState(true);
  const [showMarks, setShowMarks] = useState(true);
  const [view, setView] = useState<"both" | "raw" | "flat">("both");
  const marks = r.candidates.filter((x) => !x.below_threshold && x.kind !== "likely_variability").flatMap((x) => {
    const t = r.series.flattened.time;
    if (!t.length) return [];
    const lo = t[0], hi = t[t.length - 1];
    const out: number[] = [];
    for (let k = Math.ceil((lo - x.t0) / x.period); x.t0 + k * x.period <= hi; k++) out.push(x.t0 + k * x.period);
    return out.map((tt) => ({ type: "line", x0: tt, x1: tt, yref: "paper", y0: 0, y1: 1, line: { color: c.c2, width: 1, dash: "dot" } }));
  });
  const xTitle = `Time (${r.series.time_format}, days)`;
  return (
    <div>
      <div className="row" role="group" aria-label="Light curve display options">
        <label className="row" style={{ margin: 0 }}><input type="checkbox" checked={showTrend} onChange={(e) => setShowTrend(e.target.checked)} /> Show detrending model</label>
        <label className="row" style={{ margin: 0 }}><input type="checkbox" checked={showMarks} onChange={(e) => setShowMarks(e.target.checked)} /> Mark predicted transit times</label>
        <label className="row" style={{ margin: 0 }}>View
          <select value={view} onChange={(e) => setView(e.target.value as any)} style={{ width: "auto" }} aria-label="Which light curve to show">
            <option value="both">Raw and processed</option><option value="raw">Raw only</option><option value="flat">Processed only</option>
          </select>
        </label>
      </div>
      {view !== "flat" && (
        <Plot title="Raw light curve (median-normalised, before cleaning)" xTitle={xTitle} yTitle="Flux" height={280}
              data={[{ x: r.series.raw.time, y: r.series.raw.flux, type: "scattergl", mode: "markers", marker: { size: 2, color: c.c1 }, name: "raw" },
                     ...(showTrend && r.series.trend.time.length ? [{ x: r.series.trend.time, y: r.series.trend.flux, type: "scattergl", mode: "lines", line: { color: c.c3, width: 1.5 }, name: "trend" }] : [])]}
              caption="Quality-flagged and non-finite cadences are shown here but removed from the processed series." />
      )}
      {view !== "raw" && (
        <Plot title="Processed light curve (flagged data removed, detrended)" xTitle={xTitle} yTitle="Flattened flux" height={280}
              shapes={showMarks ? marks : []}
              data={[{ x: r.series.flattened.time, y: r.series.flattened.flux, type: "scattergl", mode: "markers", marker: { size: 2, color: c.c1 }, name: "flattened" }]}
              caption="Dotted lines mark predicted transit times of signals above the detection threshold." />
      )}
    </div>
  );
}

function Periodogram({ a }: { a: Analysis }) {
  const r = a.result!;
  const c = useColors();
  const [pass, setPass] = useState(1);
  const sp = r.periodograms.find((p) => p.rank === pass) ?? r.periodograms[0];
  const cand = r.candidates.find((x) => x.rank === sp.rank);
  return (
    <div>
      <div className="field" style={{ maxWidth: 260 }}>
        <label htmlFor="pass">Search pass</label>
        <select id="pass" value={sp.rank} onChange={(e) => setPass(Number(e.target.value))}>
          {r.periodograms.map((p) => <option key={p.rank} value={p.rank}>Pass {p.rank}{p.rank > 1 ? " (earlier signals masked)" : ""}</option>)}
        </select>
      </div>
      <Plot title="BLS power (trend-removed)" xTitle="Period (days)" yTitle="Power − running median" xType="log" height={320}
            shapes={cand ? [{ type: "line", x0: cand.period, x1: cand.period, yref: "paper", y0: 0, y1: 1, line: { color: c.c3, width: 1, dash: "dash" } }] : []}
            data={[{ x: sp.period, y: sp.sde_flattened, type: "scatter", mode: "lines", line: { color: c.c1, width: 1 }, name: "BLS power" }]}
            caption={cand ? `Highest peak: P = ${fmt(cand.period, 6)} d, SDE ${fmt(cand.sde, 3)}${cand.below_threshold ? " (below the detection threshold)" : ""}. Search range ${fmt(r.search?.period_range?.[0] ?? 0, 3)}–${fmt(r.search?.period_range?.[1] ?? 0, 3)} d.` : undefined} />
      <p className="small muted">A periodogram peak is a hint, not evidence of a planet: stellar variability, instrument systematics and eclipsing binaries all produce peaks.</p>
    </div>
  );
}

function Candidates({ a }: { a: Analysis }) {
  const r = a.result!;
  const [sel, setSel] = useState(0);
  const c = r.candidates[sel];
  return (
    <div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>#</th><th>Classification</th><th>Period (d)</th><th>Depth (ppm)</th><th>Duration (h)</th><th>SDE</th><th>Transits</th><th>Vetting</th><th></th></tr></thead>
          <tbody>
            {r.candidates.map((x, i) => (
              <tr key={x.rank} style={i === sel ? { background: "var(--surface-2)" } : undefined}>
                <td>{x.rank}</td>
                <td><span className={`badge ${KIND[x.kind]?.tone ?? ""}`}>{KIND[x.kind]?.label ?? x.kind}</span></td>
                <td className="num">{fmt(x.period, 7)}</td><td className="num">{fmt(x.depth * 1e6, 4)}</td>
                <td className="num">{fmt(x.duration * 24, 3)}</td><td className="num">{fmt(x.sde, 3)}</td>
                <td className="num">{x.n_transits_observed}</td>
                <td className="small">{x.vetting.n_fail} fail · {x.vetting.n_warn} warn</td>
                <td><button onClick={() => setSel(i)} aria-pressed={i === sel}>Inspect</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {c && <CandidateDetail c={c} />}
    </div>
  );
}

function CandidateDetail({ c }: { c: Candidate }) {
  const col = useColors();
  const f = c.fit && c.fit.ok ? c.fit : null;
  const hrs = c.folded.phase.map((p) => p * 24);
  const unc = (p: { value: number; err: number | null }, d = 6) => (p.err === null ? `${fmt(p.value, d)} (unconstrained)` : `${fmt(p.value, d)} ± ${fmt(p.err, 2)}`);
  return (
    <section className="card" style={{ marginTop: 16 }} aria-label={`Signal ${c.rank} details`}>
      <div className="row"><h3 style={{ margin: 0 }}>Signal {c.rank}</h3><span className={`badge ${KIND[c.kind]?.tone ?? ""}`}>{KIND[c.kind]?.label}</span></div>
      <p>{c.status_text}</p>
      {c.vetting.catalog_match && <p className="small">Catalogue match: <b>{c.vetting.catalog_match.name}</b> ({c.vetting.catalog_match.status}). A period match is consistent with that entry but does not independently confirm it.</p>}
      <div className="grid2" style={{ alignItems: "start" }}>
        <div>
          <Plot title="Phase-folded light curve with model" xTitle="Hours from mid-transit" yTitle="Flux" height={320}
                data={[{ x: hrs, y: c.folded.flux, error_y: { type: "data", array: c.folded.err, visible: true, thickness: 1, color: col.muted }, type: "scatter", mode: "markers", marker: { size: 5, color: col.c1 }, name: "binned data" },
                       ...(c.model ? [{ x: c.model.phase.map((p) => p * 24), y: c.model.flux, type: "scatter", mode: "lines", line: { color: col.c3, width: 2 }, name: "fitted model" }] : [])]} />
          {f?.derived.planet_radius_earth && (
            <div style={{ marginTop: 16 }}>
              <h4 style={{ marginTop: 0 }}>Size to scale (from this fit)</h4>
              <PlanetWireframe height={240} planets={[{ name: `Signal ${c.rank}`, radius: f.derived.planet_radius_earth.value, err: f.derived.planet_radius_earth.err,
                note: `Depends on the stellar radius you supplied (${f.derived.planet_radius_earth.stellar_radius_rsun} R☉). An unvalidated signal, not a confirmed planet.` }]} />
            </div>
          )}
          {!c.model && <p className="small muted">No model fit for this signal ({c.below_threshold ? "below the detection threshold" : "fit not requested or failed"}).</p>}
        </div>
        <div>
          <h4 style={{ marginTop: 0 }}>Search measurements</h4>
          <dl className="kv">
            <dt>Period (BLS)</dt><dd className="num">{fmt(c.period, 8)} d</dd>
            <dt>Mid-transit (T0)</dt><dd className="num">{fmt(c.t0, 8)}{c.t0_absolute_jd ? ` (JD ${fmt(c.t0_absolute_jd, 11)})` : " (relative time)"}</dd>
            <dt>Box depth</dt><dd className="num">{fmt(c.depth * 1e6, 5)} ppm (S/N {fmt(c.depth_snr, 3)})</dd>
            <dt>Duration</dt><dd className="num">{fmt(c.duration * 24, 4)} h</dd>
            <dt>Signal strength</dt><dd className="num">SDE {fmt(c.sde, 4)}</dd>
          </dl>
          {f && (
            <>
              <h4>Transit model fit</h4>
              <div className="table-wrap"><table>
                <thead><tr><th>Parameter</th><th>Value</th><th>How uncertainty was obtained</th></tr></thead>
                <tbody>
                  {([["period", "Period (d)", 7], ["t0", "T0 (reference epoch)", 7], ["rp_rs", "Rp/R★", 4], ["a_rs", "a/R★", 3], ["b", "Impact parameter b", 3]] as const).map(([k, label, d]) => (
                    <tr key={k}><td>{label}</td><td className="num">{unc(f.params[k], d)}</td><td className="small muted">{f.params[k].method}</td></tr>
                  ))}
                </tbody>
              </table></div>
              <dl className="kv" style={{ marginTop: 8 }}>
                <dt>Reduced χ²</dt><dd className="num">{fmt(f.reduced_chi2, 3)}</dd>
                <dt>Implied stellar density</dt><dd className="num">{fmt(f.derived.stellar_density_solar, 3)} ρ☉ (if circular)</dd>
                <dt>Planet radius</dt>
                <dd>{f.derived.planet_radius_earth ? <span className="num">{fmt(f.derived.planet_radius_earth.value, 3)} ± {fmt(f.derived.planet_radius_earth.err, 2)} R⊕ (R★ = {f.derived.planet_radius_earth.stellar_radius_rsun} R☉, supplied)</span> : <span className="muted">Not computed: no stellar radius supplied</span>}</dd>
              </dl>
              {f.flags.map((x, i) => <div key={i} className="notice warn small">{x}</div>)}
              <details><summary>Model assumptions</summary><ul className="small">{f.assumptions.map((x) => <li key={x}>{x}</li>)}<li>Limb darkening: {f.limb_darkening.note}</li></ul></details>
            </>
          )}
        </div>
      </div>
      <h4>Vetting checks</h4>
      <p className="small muted">Screening heuristics for common false positives. Passing them does not validate a planet.</p>
      <ul className="checks">{c.vetting.checks.map((k, i) => <li key={i}><span className={`badge ${k.status === "na" ? "" : k.status}`}>{k.status}</span><span><b>{k.id.replace(/_/g, " ")}</b>: {k.detail}</span></li>)}</ul>
    </section>
  );
}

function Provenance({ a }: { a: Analysis }) {
  const p = a.result!.provenance;
  const pre = p.preprocessing_pass2 ?? p.preprocessing_pass1;
  return (
    <div className="grid2" style={{ alignItems: "start" }}>
      <div className="card">
        <h3>Input data</h3>
        <dl className="kv">
          <dt>Dataset</dt><dd><Link href={`/datasets/${a.dataset_id}`}>{p.dataset.name}</Link> ({p.dataset.source})</dd>
          <dt>SHA-256</dt><dd className="mono" style={{ wordBreak: "break-all" }}>{p.dataset.sha256}</dd>
          <dt>Category</dt><dd>{p.input_schema.category} ({Math.round(p.input_schema.confidence * 100)}% confidence)</dd>
          <dt>Time / flux</dt><dd className="mono">{p.input_schema.roles.time?.column} / {p.input_schema.roles.flux?.column}</dd>
          <dt>Flux convention</dt><dd>{p.input_schema.flux_kind}</dd>
          <dt>Manual mapping</dt><dd className="mono">{Object.keys(p.manual_mapping).length ? JSON.stringify(p.manual_mapping) : "none"}</dd>
          {p.dataset.provenance?.obsid && <><dt>Archive observation</dt><dd className="mono">{p.dataset.provenance.archive} obsid {p.dataset.provenance.obsid}</dd></>}
        </dl>
        {p.uncertainties_estimated_from_scatter && <div className="notice warn small">The input had no flux uncertainties; they were estimated from point-to-point scatter.</div>}
        <h4>Library versions</h4>
        <dl className="kv">{Object.entries(p.versions).map(([k, v]) => <><dt key={k + "k"}>{k}</dt><dd key={k + "v"} className="mono">{String(v)}</dd></>)}</dl>
      </div>
      <div className="card">
        <h3>Processing record</h3>
        <h4 style={{ marginTop: 0 }}>Parameters used</h4>
        <pre className="small mono" style={{ overflow: "auto", margin: 0 }}>{JSON.stringify(p.parameters, null, 2)}</pre>
        <h4>Preprocessing (final pass)</h4>
        <pre className="small mono" style={{ overflow: "auto", margin: 0 }}>{JSON.stringify(pre, null, 2)}</pre>
        <p className="small muted">The original observations are never modified; all processing operates on copies. {p.library_note}</p>
      </div>
    </div>
  );
}

function Downloads({ a }: { a: Analysis }) {
  const items = [
    ["export.json", "Full results (JSON)", "Machine-readable: candidates, fits, vetting, series, periodograms and complete provenance."],
    ["candidates.csv", "Candidate table (CSV)", "One row per signal with period, epoch, depth, S/N, SDE and fitted parameters."],
    ["report.html", "Report (HTML)", "Self-contained, human-readable report with figures, assumptions and limitations."],
  ];
  return (
    <div className="card">
      <ul className="checks">
        {items.map(([f, t, d]) => (
          <li key={f} style={{ justifyContent: "space-between", alignItems: "center" }}>
            <span><b>{t}</b><div className="small muted">{d}</div></span>
            <a className="btn" href={`/api/analyses/${a.id}/${f}`} download>Download</a>
          </li>
        ))}
      </ul>
      <p className="small muted">To reproduce this analysis, re-run the same dataset with the parameters listed under Data &amp; provenance; results are deterministic for identical inputs and library versions.</p>
    </div>
  );
}
