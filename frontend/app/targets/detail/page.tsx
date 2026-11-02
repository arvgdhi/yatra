"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Fragment, Suspense, useEffect, useMemo, useState } from "react";
import Loading from "@/components/Loading";
import Plot, { useColors } from "@/components/Plot";
import PlanetWireframe from "@/components/PlanetWireframe";
import { ApiError, fmt, get, post, when } from "@/lib/api";
import type { Dataset, Observation, TargetDetail, Val } from "@/lib/types";

type Product = { filename: string; uri: string; size_bytes: number | null; description: string | null };

const v = (x: Val, d = 5) => (x ? `${fmt(x.value, d)}${x.err_plus != null || x.err_minus != null ? ` (+${fmt(x.err_plus, 2)} / ${fmt(x.err_minus, 2)})` : ""} ${(x.unit ?? "").replace("R_earth", "R⊕").replace("R_sun", "R☉").replace("M_earth", "M⊕").replace("M_sun", "M☉")}` : "—");
function Value({ value, digits = 5 }: { value: Val; digits?: number }) {
  if (!value) return <>—</>;
  return <><span>{v(value, digits)}</span>{value.calculated && <span className="badge estimate" title={value.estimate?.uncertainty_note}>ML estimate{value.estimate?.error_factor ? ` ×/÷ ${value.estimate.error_factor.toFixed(2)}` : ""}</span>}</>;
}

function Inner() {
  const key = useSearchParams().get("key") ?? "";
  const router = useRouter();
  const [t, setT] = useState<TargetDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [prods, setProds] = useState<Record<string, Product[] | "loading" | string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const col = useColors();

  useEffect(() => {
    if (!key) return;
    setT(null); setErr(null);
    get<TargetDetail>(`/api/targets/detail?key=${encodeURIComponent(key)}`)
      .then(setT).catch((e) => setErr(e instanceof ApiError ? e.message : "Could not load target"));
  }, [key]);


  const wire = useMemo(() => (t?.published_planets ?? []).map((p) => ({
    name: p.name, radius: p.radius?.value ?? null, err: p.radius?.err_plus ?? null, note: p.radius?.calculated ? "Locally calculated approximate radius; not an archive measurement." : "Published value from the NASA Exoplanet Archive.",
  })), [t]);
  const scatter = useMemo(() => {
    if (!t) return [];
    const pl = t.published_planets.filter((p) => p.period && p.radius);
    const cand = t.catalog_candidates.filter((c) => c.period && c.radius_earth);
    const out: any[] = [];
    if (pl.length) out.push({ x: pl.map((p) => p.period!.value), y: pl.map((p) => p.radius!.value), text: pl.map((p) => p.name), type: "scatter", mode: "markers",
      marker: { size: 11, color: col.c1 }, name: "published planets", hovertemplate: "%{text}<br>P = %{x} d<br>R = %{y} R⊕<extra></extra>" });
    if (cand.length) out.push({ x: cand.map((c) => c.period!), y: cand.map((c) => c.radius_earth!), text: cand.map((c) => c.name), type: "scatter", mode: "markers",
      marker: { size: 10, color: col.c2, symbol: "diamond-open", line: { width: 2 } }, name: "catalogue candidates", hovertemplate: "%{text}<br>P = %{x} d<br>R = %{y} R⊕<extra></extra>" });
    return out;
  }, [t, col]);
  const timeline = useMemo(() => {
    if (!t) return [];
    const all = Object.entries(t.observations).flatMap(([g, obs]) => obs.filter((o) => o.start_date && o.end_date).map((o) => ({ g, o })));
    if (!all.length) return [];
    return [{ type: "bar", orientation: "h", y: all.map(({ g, o }) => `${g}${o.sequence != null ? " " + o.sequence : ""}`),
      base: all.map(({ o }) => o.start_date), x: all.map(({ o }) => Math.max(Date.parse(o.end_date!) - Date.parse(o.start_date!), 86400000)),
      marker: { color: all.map(({ o }) => (o.analysis_supported ? col.c1 : col.muted)) },
      text: all.map(({ o }) => o.analysis_supported ? "analysable" : "not supported"), hovertemplate: "%{y}<br>%{text}<extra></extra>", showlegend: false }];
  }, [t, col]);

  async function showProducts(o: Observation) {
    setOpen(o.obsid === open ? null : o.obsid);
    if (prods[o.obsid]) return;
    setProds((p) => ({ ...p, [o.obsid]: "loading" }));
    try {
      const r = await get<{ products: Product[] }>(`/api/observations/${o.obsid}/products`);
      setProds((p) => ({ ...p, [o.obsid]: r.products }));
    } catch (e) {
      setProds((p) => ({ ...p, [o.obsid]: e instanceof ApiError ? e.message : "Failed to list products" }));
    }
  }

  async function importProduct(o: Observation, p: Product) {
    setBusy(p.uri);
    try {
      const ds = await post<Dataset>("/api/observations/import", {
        obsid: o.obsid, uri: p.uri, filename: p.filename, size_bytes: p.size_bytes, target_label: t?.label, mission: o.mission,
      });
      router.push(`/datasets/${ds.id}?target=${encodeURIComponent(key)}`);
    } catch (e) {
      setProds((x) => ({ ...x, [o.obsid]: e instanceof ApiError ? e.message : "Import failed" }));
      setBusy(null);
    }
  }

  if (!key) return <div className="empty">No target selected. <Link href="/targets">Search for one</Link>.</div>;
  if (err) return <div className="notice error" role="alert">{err}</div>;
  if (!t) return <Loading title="Fetching target data" steps={["NASA Exoplanet Archive", "MAST", "Exo.MAST"]} />;

  const groups = Object.entries(t.observations);
  return (
    <div>
      <p className="small muted crumbs"><Link href="/targets">Targets</Link> / {t.label}</p>
      <header className="page-head">
        <h1>{t.label}</h1>
        <div className="stats">
          <div className="stat"><span className="num">{t.published_planets.length}</span><span>published planet{t.published_planets.length === 1 ? "" : "s"}</span></div>
          <div className="stat"><span className="num">{t.catalog_candidates.length}</span><span>catalogued candidate{t.catalog_candidates.length === 1 ? "" : "s"}</span></div>
          <div className="stat"><span className="num">{t.n_observations}</span><span>observation{t.n_observations === 1 ? "" : "s"}</span></div>
        </div>
      </header>
      <p className="muted small">
        {t.position.ra_deg != null ? <>RA {fmt(t.position.ra_deg, 7)}°, Dec {fmt(t.position.dec_deg, 7)}° (ICRS)</> : "Sky position unavailable"}
        {t.aliases.length > 0 && <> · Also known as: {t.aliases.slice(0, 8).join(", ")}</>}
      </p>
      {t.errors.map((e, i) => (
        <div key={i} className="notice warn" role="status">
          <b>{e.source}</b>: {e.message}{e.retriable ? " (temporary; reload to retry). Other sources are shown below." : ""}
        </div>
      ))}
      {t.estimate_model && <div className="notice estimate-notice" role="status"><span className="badge estimate">Local ML estimates</span> {t.estimate_model.estimates} missing value{t.estimate_model.estimates === 1 ? "" : "s"} approximated with the checked-in local model. They are not measurements, detections, or confirmation.</div>}

      <div className="grid2 even">
        <section className="card" aria-labelledby="h-star">
          <h2 id="h-star" className="card-title">Host star</h2>
          {t.star ? (
            <>
              <div className="star-groups">
                <div className="star-group"><p className="star-label">Identity</p><dl className="kv"><dt>Name</dt><dd>{t.star.name}</dd><dt>Position</dt><dd className="num">{t.position.ra_deg != null ? `${fmt(t.position.ra_deg, 6)}°, ${fmt(t.position.dec_deg, 6)}°` : "—"}</dd></dl></div>
                <div className="star-group"><p className="star-label">Temperature</p><dl className="kv"><dt>Effective temperature</dt><dd className="num">{v(t.star.teff, 4)}</dd></dl></div>
                <div className="star-group"><p className="star-label">Physical properties</p><dl className="kv"><dt>Radius</dt><dd className="num">{v(t.star.radius, 4)}</dd><dt>Mass</dt><dd className="num">{v(t.star.mass, 3)}</dd><dt>Distance</dt><dd className="num">{v(t.star.distance, 5)}</dd></dl></div>
                {Object.keys(t.star.ids).length > 0 && <div className="star-group"><p className="star-label">Catalogue identifiers</p><dl className="kv">{Object.entries(t.star.ids).map(([k, x]) => <Fragment key={k}><dt>{k.replaceAll("_", " ")}</dt><dd className="mono">{x}</dd></Fragment>)}</dl></div>}
              </div>
              {t.star.reference && <p className="small muted" style={{ marginBottom: 0 }}>Source: NASA Exoplanet Archive composite parameters ({t.star.reference})</p>}
            </>
          ) : <p className="muted" style={{ margin: 0 }}>No host-star record in the confirmed-planet catalogue.</p>}
        </section>
        <section className="card" aria-labelledby="h-size">
          <h2 id="h-size" className="card-title">Planet size to scale</h2>
          <PlanetWireframe planets={wire} />
        </section>
      </div>

      {(scatter.length > 0 || timeline.length > 0) && (
        <>
          <h2>Graphs</h2>
          <div className="grid2 even">
            {scatter.length > 0 && (
              <section className="card" aria-label="Orbital period versus planet radius">
                <Plot title="Planet radius vs revolution period" xTitle="Revolution period (days)" yTitle="Radius (R⊕)" xType="log" height={300} data={scatter}
                      caption="Archive values; points without both a period and a radius are not shown." />
              </section>
            )}
            {timeline.length > 0 && (
              <section className="card" aria-label="Observation timeline">
                <Plot title="Observation coverage by sector / quarter" xTitle="Date" yTitle="" xType="date" yType="category" height={300} data={timeline}
                      extraLayout={{ yaxis: { autorange: "reversed", automargin: true, color: col.text, tickfont: { size: 10 } }, bargap: 0.25 }}
                      caption="Dark bars can be imported and analysed here; grey bars are not supported for transit analysis." />
              </section>
            )}
          </div>
          <p className="small muted graph-note">These charts compare the published planetary system and show when public observations cover this target. See the Guide for how to read them.</p>
        </>
      )}

      <h2>Published planets</h2>
      {t.published_planets.length ? (
        <div className="table-wrap"><table>
          <thead><tr><th>Planet</th><th>Status</th><th>Revolution period</th><th>Radius</th><th>Mass</th><th>Transit duration</th><th>Discovery</th></tr></thead>
          <tbody>{t.published_planets.map((p) => (
            <tr key={p.name}><td><b>{p.name}</b></td><td><span className="badge strong">confirmed (archive)</span></td>
              <td className="num"><Value value={p.period} digits={7} /></td><td className="num"><Value value={p.radius} digits={4} /></td><td className="num"><Value value={p.mass} digits={4} /></td>
              <td className="num"><Value value={p.transit_duration} digits={3} /></td>
              <td className="small">{[p.discovery.method, p.discovery.year, p.discovery.facility].filter(Boolean).join(" · ") || "—"}</td></tr>
          ))}</tbody>
        </table></div>
      ) : <p className="muted">No confirmed planets are listed for this target.</p>}

      {t.catalog_candidates.length > 0 && (
        <>
          <h2>Catalogued candidates</h2>
          <p className="small muted">Entries from the TESS Objects of Interest / Kepler KOI tables. These are candidates unless the archive marks them confirmed.</p>
          <div className="table-wrap"><table>
            <thead><tr><th>Name</th><th>Catalogue</th><th>Disposition</th><th>Revolution period (d)</th><th>Depth (ppm)</th><th>Radius (R⊕)</th></tr></thead>
            <tbody>{t.catalog_candidates.map((c) => (
              <tr key={c.name}><td>{c.name}</td><td className="small">{c.catalog}</td>
                <td><span className={`badge ${c.status === "confirmed" ? "strong" : c.status === "false_positive" ? "fail" : "warn"}`}>{c.disposition ?? c.status}</span></td>
                <td className="num">{fmt(c.period, 7)}</td><td className="num">{fmt(c.depth_ppm, 4)}</td><td className="num">{fmt(c.radius_earth, 3)}</td></tr>
            ))}</tbody>
          </table></div>
        </>
      )}

      <h2>Available observations</h2>
      {t.n_observations === 0 && <div className="empty">No TESS, Kepler or K2 time-series observations were found in MAST for this position{t.errors.some((e) => e.source === "MAST") ? " (the MAST query failed, see above)" : ""}.</div>}
      {groups.map(([g, obs]) => (
        <div className="card" key={g}>
          <h3>{g} <span className="small muted">({obs.length} observation{obs.length > 1 ? "s" : ""})</span></h3>
          <div className="table-wrap"><table>
            <thead><tr><th>Seq.</th><th>Dates</th><th>Cadence</th><th>Target</th><th></th></tr></thead>
            <tbody>{obs.map((o) => (
              <Fragment key={o.obsid}>
                <tr>
                  <td className="num">{o.sequence ?? "—"}</td><td className="num">{o.start_date ?? "—"} → {o.end_date ?? "—"}</td>
                  <td className="num">{o.exposure_s ? `${fmt(o.exposure_s, 4)} s` : "—"}</td><td className="small">{o.target_name}</td>
                  <td>{o.analysis_supported
                    ? <button onClick={() => showProducts(o)} aria-expanded={open === o.obsid}>Light-curve files</button>
                    : <span className="small muted" title={o.unsupported_reason ?? ""}>not supported for analysis</span>}</td>
                </tr>
                {open === o.obsid && (
                  <tr><td colSpan={5} style={{ background: "var(--surface-2)" }}>
                    {prods[o.obsid] === "loading" && <span role="status">Listing products…</span>}
                    {typeof prods[o.obsid] === "string" && prods[o.obsid] !== "loading" && <span className="notice error" role="alert">{String(prods[o.obsid])}</span>}
                    {Array.isArray(prods[o.obsid]) && ((prods[o.obsid] as Product[]).length === 0
                      ? <span className="muted">No light-curve files found for this observation.</span>
                      : (prods[o.obsid] as Product[]).map((p) => (
                        <div key={p.uri} className="row" style={{ padding: "4px 0" }}>
                          <span className="mono small">{p.filename}</span>
                          <span className="small muted">{p.size_bytes ? `${(p.size_bytes / 1e6).toFixed(1)} MB` : ""}</span><span className="spacer" />
                          <button className="primary" disabled={busy === p.uri} onClick={() => importProduct(o, p)}>{busy === p.uri ? "Downloading…" : "Load and inspect"}</button>
                        </div>)))}
                  </td></tr>
                )}
              </Fragment>
            ))}</tbody>
          </table></div>
        </div>
      ))}

      <h2>Sources</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>Archive query</th><th>Retrieved</th><th>Cache</th></tr></thead>
        <tbody>{t.provenance.map((p, i) => <tr key={i}><td>{p.source}</td><td className="num">{when(p.retrieved_at)}</td><td>{p.from_cache ? "served from local cache" : "live"}</td></tr>)}</tbody>
      </table></div>
      {t.notes.map((n) => <p key={n} className="small muted">{n}</p>)}
    </div>
  );
}
export default function Page() { return <Suspense fallback={<Loading title="Loading" />}><Inner /></Suspense>; }
