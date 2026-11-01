"use client";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import ParamsForm, { buildParams } from "@/components/ParamsForm";
import Plot from "@/components/Plot";
import { useColors } from "@/components/Plot";
import ProfileView from "@/components/ProfileView";
import { ApiError, get, post, when } from "@/lib/api";
import type { Analysis, Dataset } from "@/lib/types";

type Preview = { kind: "lightcurve" | "none"; time?: number[]; flux?: number[]; time_format?: string; n_points?: number; n_shown?: number; reason?: string };

function Inner() {
  const { id } = useParams<{ id: string }>();
  const target = useSearchParams().get("target");
  const router = useRouter();
  const colors = useColors();
  const [ds, setDs] = useState<Dataset | null>(null);
  const [pv, setPv] = useState<Preview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [vals, setVals] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const d = await get<Dataset>(`/api/datasets/${id}`);
      setDs(d);
      setPv(await get<Preview>(`/api/datasets/${id}/preview`).catch(() => ({ kind: "none", reason: "Preview unavailable for this mapping." } as Preview)));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load dataset");
    }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  if (err) return <div className="notice error" role="alert">{err} <Link href="/upload">Upload a file</Link></div>;
  if (!ds) return <p role="status">Loading dataset…</p>;

  const opt = ds.analysis_options.find((o) => o.status === "available");
  const mod = opt?.module;

  async function remap(m: Record<string, string>) {
    setBusy(true);
    try {
      setDs(await post<Dataset>(`/api/datasets/${id}/mapping`, { mapping: m }));
      setPv(await get<Preview>(`/api/datasets/${id}/preview`).catch(() => ({ kind: "none" } as Preview)));
    } catch (e) { setErr(e instanceof ApiError ? e.message : "Mapping failed"); }
    setBusy(false);
  }

  async function run() {
    if (!mod) return;
    setRunning(true); setErr(null);
    try {
      const a = await post<Analysis>("/api/analyses", { dataset_id: id, module_id: mod.id, params: buildParams(mod.parameters, vals), target_key: target });
      router.push(`/analyses/${a.id}`);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not start the analysis");
      setRunning(false);
    }
  }

  return (
    <div>
      <p className="small muted"><Link href="/">Explore</Link> / Dataset</p>
      <h1>{ds.name}</h1>
      <p className="muted small">
        {ds.source === "archive" ? "Archive product" : "Uploaded file"} · {(ds.size_bytes / 1024).toFixed(0)} KB · sha256 <code>{ds.sha256.slice(0, 16)}…</code> · added {when(ds.created_at)}
        {ds.source === "upload" && " · stored temporarily and removed automatically"}
      </p>
      {ds.source === "archive" && (
        <div className="notice">
          Source: {String(ds.provenance.archive)} observation <code>{String(ds.provenance.obsid)}</code>, retrieved {String(ds.provenance.retrieved_at)}.
          {target && <> Catalogue planets for this target will be used to label matching signals.</>}
        </div>
      )}
      {err && <div className="notice error" role="alert">{err}</div>}

      <div className="grid2" style={{ alignItems: "start", marginTop: 16 }}>
        <div className="card"><ProfileView profile={ds.profile} mapping={ds.mapping} onMap={remap} busy={busy} /></div>
        <div>
          <div className="card">
            <h3>Data preview</h3>
            {pv?.kind === "lightcurve" && pv.time ? (
              <Plot title="Light curve (normalised flux)" xTitle={`Time (${pv.time_format}, days)`} yTitle="Flux" height={260}
                    data={[{ x: pv.time, y: pv.flux, type: "scattergl", mode: "markers", marker: { size: 2, color: colors.c1 }, name: "flux" }]}
                    caption={`${pv.n_shown?.toLocaleString()} of ${pv.n_points?.toLocaleString()} points shown.`} />
            ) : <div className="empty">{pv?.reason ?? "No preview available for this data type."}</div>}
          </div>
          <div className="card">
            <h3>Analysis</h3>
            {ds.profile.applicable_methods.map((m) => (
              <div key={m.id} className="row" style={{ marginBottom: 6 }}>
                <span className={`badge ${m.status}`}>{m.status}</span><b>{m.name}</b>
                {m.reason && <span className="small muted">{m.reason}</span>}
              </div>
            ))}
            {!ds.profile.applicable_methods.length && <p className="muted">No analysis method applies to this data. {ds.profile.limitations[0]}</p>}
            {mod && (
              <>
                <p className="small">{mod.description}</p>
                <details><summary>Assumptions and limitations</summary>
                  <ul className="small">{mod.assumptions.map((a) => <li key={a}>{a}</li>)}{mod.limitations.map((a) => <li key={a}>{a}</li>)}</ul>
                </details>
                <div style={{ marginTop: 12 }}><ParamsForm params={mod.parameters} values={vals} onChange={setVals} /></div>
                <p className="small muted">Supplying the stellar radius (advanced) is required for a planet radius estimate; without it only Rp/R★ is reported.</p>
                <button className="primary" onClick={run} disabled={running || ds.profile.needs_confirmation && !Object.keys(ds.mapping).length}>
                  {running ? "Starting…" : "Run transit analysis"}
                </button>
                {ds.profile.needs_confirmation && !Object.keys(ds.mapping).length && (
                  <span className="small muted"> Confirm the column mapping first.</span>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p role="status">Loading…</p>}><Inner /></Suspense>;
}
