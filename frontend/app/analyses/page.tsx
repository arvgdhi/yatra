"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { get, when } from "@/lib/api";

type Row = { id: string; dataset_id: string; module_id: string; status: string; created_at: number; finished_at: number | null; error: string | null; original_name: string | null; source: string | null };

export default function AnalysesPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { get<Row[]>("/api/analyses").then(setRows).catch((e) => setErr(e.message)); }, []);
  return (
    <div>
      <h1>My analyses</h1>
      <p className="muted">Every analysis keeps its inputs, parameters and results, so it can be reopened and reproduced.</p>
      {err && <div className="notice error" role="alert">{err}</div>}
      {rows === null && !err && <p role="status">Loading…</p>}
      {rows?.length === 0 && <div className="empty">No analyses yet. <Link href="/upload">Upload a file</Link> or <Link href="/targets">search a target</Link> to start.</div>}
      {rows && rows.length > 0 && (
        <div className="table-wrap"><table>
          <thead><tr><th>Started</th><th>Dataset</th><th>Source</th><th>Method</th><th>Status</th><th></th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.id}>
              <td className="num">{when(r.created_at)}</td><td>{r.original_name ?? r.dataset_id}</td><td>{r.source ?? "—"}</td><td>{r.module_id}</td>
              <td><span className={`badge ${r.status === "succeeded" ? "pass" : r.status === "failed" ? "fail" : "warn"}`}>{r.status}</span>{r.error && <div className="small muted">{r.error}</div>}</td>
              <td><Link href={`/analyses/${r.id}`}>Open</Link></td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </div>
  );
}
