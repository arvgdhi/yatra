"use client";
import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import TargetSearch from "@/components/TargetSearch";
import { get } from "@/lib/api";
import Loading, { Spinner } from "@/components/Loading";

type Recent = { target_key: string; label: string; kind: string; visited_at: number };

function Inner() {
  const q = useSearchParams().get("q");
  const [recent, setRecent] = useState<Recent[]>([]);
  const [hits, setHits] = useState<{ key: string; host: string; planets: string[]; source: string; note?: string }[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { get<Recent[]>("/api/targets/recent").then(setRecent).catch(() => {}); }, []);
  useEffect(() => {
    if (!q) return;
    setHits(null); setErr(null);
    get<{ results: any[]; errors: { source: string; message: string }[] }>(`/api/targets/search?q=${encodeURIComponent(q)}`)
      .then((r) => { setHits(r.results); if (r.errors.length) setErr(r.errors.map((e) => `${e.source}: ${e.message}`).join("; ")); })
      .catch((e) => setErr(String(e.message ?? e)));
  }, [q]);
  return (
    <div style={{ maxWidth: 860 }}>
      <h1>Targets</h1>
      <p className="muted">Search by star name, planet name or catalogue identifier (TIC, TOI, KIC, KOI). A catalogue entry does not mean observations exist; availability is checked in MAST for each target.</p>
      <div className="card"><TargetSearch autoFocus /></div>
      {q && (
        <section style={{ marginTop: 20 }} aria-live="polite">
          <h2>Results for “{q}”</h2>
          {err && <div className="notice warn" role="status">{err}</div>}
          {hits === null && !err && <Spinner label="Searching NASA Exoplanet Archive and MAST…" />}
          {hits?.length === 0 && <div className="empty">No match in the exoplanet catalogues or the MAST name resolver.</div>}
          {hits?.map((h) => (
            <div className="card" key={h.key}>
              <div className="row"><b>{h.host}</b><span className="small muted">{h.source}</span><span className="spacer" />
                <Link className="btn primary" href={`/targets/detail?key=${encodeURIComponent(h.key)}`}>Open</Link></div>
              <div className="small muted">{h.planets.length ? `Known planets: ${h.planets.join(", ")}` : h.note ?? ""}</div>
            </div>
          ))}
        </section>
      )}
      <h2>Recently explored</h2>
      {recent.length ? (
        <div className="table-wrap"><table><tbody>
          {recent.map((r) => <tr key={r.target_key}><td><Link href={`/targets/detail?key=${encodeURIComponent(r.target_key)}`}>{r.label}</Link></td><td className="muted small">{new Date(r.visited_at * 1000).toLocaleString()}</td></tr>)}
        </tbody></table></div>
      ) : <p className="muted small">No targets opened yet.</p>}
    </div>
  );
}
export default function Page() { return <Suspense fallback={<Loading title="Loading" />}><Inner /></Suspense>; }
