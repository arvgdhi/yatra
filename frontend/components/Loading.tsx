"use client";

/** Indeterminate loading panel. It shows what is being contacted, not a fake percentage. */
export default function Loading({ title, steps = [] }: { title: string; steps?: string[] }) {
  return (
    <div className="loading card" role="status" aria-live="polite" aria-busy="true">
      <div className="loading-head">
        <span className="spinner" aria-hidden="true" />
        <div>
          <div className="loading-title">{title}</div>
          {steps.length > 0 && <div className="small muted">{steps.join(" · ")}</div>}
        </div>
      </div>
      <div className="skeleton-row" aria-hidden="true">
        <div className="skeleton" style={{ height: 150 }} />
        <div className="skeleton" style={{ height: 150 }} />
      </div>
      <div className="skeleton" style={{ height: 14, width: "70%", marginTop: 16 }} aria-hidden="true" />
      <div className="skeleton" style={{ height: 14, width: "55%", marginTop: 8 }} aria-hidden="true" />
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <span className="row" role="status" style={{ gap: 8 }}>
      <span className="spinner small" aria-hidden="true" />
      <span className="small muted">{label}</span>
    </span>
  );
}
