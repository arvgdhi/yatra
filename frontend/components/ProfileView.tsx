"use client";
import { useState } from "react";
import { fmt } from "@/lib/api";
import type { Profile } from "@/lib/types";

const ROLE_LABELS: Record<string, string> = {
  time: "Time", flux: "Flux", flux_err: "Flux uncertainty", quality: "Quality flag", rv: "Radial velocity",
  rv_err: "RV uncertainty", wavelength: "Wavelength", ra: "RA", dec: "Dec",
};
const MAPPABLE = ["time", "flux", "flux_err", "quality"];

export default function ProfileView({
  profile, mapping, onMap, busy,
}: { profile: Profile; mapping: Record<string, string>; onMap: (m: Record<string, string>) => void; busy: boolean }) {
  const [editing, setEditing] = useState(profile.needs_confirmation);
  const [draft, setDraft] = useState<Record<string, string>>({
    ...Object.fromEntries(MAPPABLE.map((r) => [r, mapping[r] ?? profile.roles[r]?.column ?? ""])),
    time_unit: mapping.time_unit ?? "", flux_kind: mapping.flux_kind ?? "",
  });
  const cov = profile.coverage;
  const conf = Math.round(profile.confidence * 100);

  return (
    <div>
      <div className="row">
        <h2 style={{ margin: 0 }}>{profile.category_label}</h2>
        <span className={`badge ${profile.category === "unknown" ? "fail" : conf >= 60 ? "strong" : "warn"}`}>
          {profile.category === "unknown" ? "not identified" : `${conf}% confidence`}
        </span>
      </div>

      {profile.needs_confirmation && (
        <div className="notice warn" role="status">
          <b>Please confirm how this file was read.</b>{" "}
          {profile.ambiguous ? "More than one interpretation fits the data. " : ""}
          {profile.category === "unknown" ? "The columns could not be matched to a supported measurement type. " : ""}
          Check the column mapping below.
          {profile.alternatives.length > 0 && (
            <div className="small">Other interpretations: {profile.alternatives.map((a) => `${a.label} (${Math.round(a.score * 100)}%)`).join(", ")}</div>
          )}
        </div>
      )}

      <h4>Why this classification</h4>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        {profile.evidence.map((e, i) => <li key={i} className="small"><span className="muted">{e.kind}:</span> {e.text}</li>)}
        {!profile.evidence.length && <li className="small muted">No supporting evidence found.</li>}
      </ul>

      <h4>Detected columns</h4>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Role</th><th>Column</th><th>Unit</th><th>Matched by</th></tr></thead>
          <tbody>
            {Object.entries(profile.roles).map(([role, r]) => (
              <tr key={role}>
                <td>{ROLE_LABELS[role] ?? role}</td><td className="mono">{r.column}</td><td>{r.unit ?? "—"}</td>
                <td>{r.source === "user" ? "your selection" : r.source === "alias-weak" ? "generic name (weak)" : "name"}</td>
              </tr>
            ))}
            {!Object.keys(profile.roles).length && <tr><td colSpan={4} className="muted">None recognised. Columns found: {profile.columns_found.join(", ") || "none"}</td></tr>}
          </tbody>
        </table>
      </div>
      {profile.time && (
        <p className="small muted">
          Time convention: {profile.time.format.toUpperCase()}, unit {profile.time.unit ?? "d"}
          {profile.time.offset_jd ? ` (offset JD ${fmt(profile.time.offset_jd, 10)})` : " (no absolute reference; times are relative)"}
          {profile.flux_kind ? ` · Flux convention: ${profile.flux_kind}` : ""}
        </p>
      )}

      <div className="row" style={{ marginTop: 8 }}>
        <button onClick={() => setEditing((e) => !e)} aria-expanded={editing}>{editing ? "Hide" : "Correct"} column mapping and units</button>
      </div>
      {editing && (
        <form className="card" style={{ marginTop: 10 }} onSubmit={(e) => {
          e.preventDefault();
          onMap(Object.fromEntries(Object.entries(draft).filter(([, v]) => v)));
        }}>
          <div className="grid2">
            {MAPPABLE.map((r) => (
              <div className="field" key={r}>
                <label htmlFor={`map-${r}`}>{ROLE_LABELS[r]} column</label>
                <select id={`map-${r}`} value={draft[r]} onChange={(e) => setDraft({ ...draft, [r]: e.target.value })}>
                  <option value="">{r === "time" || r === "flux" ? "— choose —" : "— none —"}</option>
                  {profile.columns_found.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            ))}
            <div className="field">
              <label htmlFor="map-tu">Time unit</label>
              <select id="map-tu" value={draft.time_unit} onChange={(e) => setDraft({ ...draft, time_unit: e.target.value })}>
                <option value="">auto-detect</option><option value="d">days</option><option value="h">hours</option>
                <option value="min">minutes</option><option value="s">seconds</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="map-fk">Flux convention</label>
              <select id="map-fk" value={draft.flux_kind} onChange={(e) => setDraft({ ...draft, flux_kind: e.target.value })}>
                <option value="">auto-detect</option><option value="relative">already normalised (≈1)</option>
                <option value="counts">counts / rate (normalise by median)</option><option value="magnitude">magnitudes</option>
              </select>
            </div>
          </div>
          <button className="primary" type="submit" disabled={busy}>{busy ? "Re-reading…" : "Apply and re-profile"}</button>
        </form>
      )}

      {cov && cov.n_valid > 0 && (
        <>
          <h4>Observation coverage</h4>
          <dl className="kv">
            <dt>Valid points</dt><dd className="num">{cov.n_valid.toLocaleString()} of {cov.n_rows.toLocaleString()}</dd>
            {cov.baseline_days !== undefined && <><dt>Baseline</dt><dd className="num">{fmt(cov.baseline_days, 5)} days</dd></>}
            {cov.median_cadence_s !== undefined && <><dt>Median cadence</dt><dd className="num">{fmt(cov.median_cadence_s / 60, 4)} min</dd></>}
            {cov.n_gaps !== undefined && <><dt>Gaps</dt><dd className="num">{cov.n_gaps} (largest {fmt(cov.largest_gap_days, 3)} d)</dd></>}
            {cov.duty_cycle !== undefined && <><dt>Duty cycle</dt><dd className="num">{Math.round(cov.duty_cycle * 100)}%</dd></>}
          </dl>
        </>
      )}

      {profile.quality_issues.length > 0 && (
        <>
          <h4>Data quality</h4>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {profile.quality_issues.map((q, i) => <li key={i} className="small"><span className={`badge ${q.severity === "error" ? "fail" : q.severity === "warning" ? "warn" : ""}`}>{q.severity}</span> {q.text}</li>)}
          </ul>
        </>
      )}
      {profile.limitations.length > 0 && (
        <>
          <h4>Limitations</h4>
          <ul style={{ margin: 0, paddingLeft: 18 }}>{profile.limitations.map((l, i) => <li key={i} className="small">{l}</li>)}</ul>
        </>
      )}
    </div>
  );
}
