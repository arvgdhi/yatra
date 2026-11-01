"use client";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { ApiError, get } from "@/lib/api";
import type { ArchiveErr, SearchResult } from "@/lib/types";

type Resp = { results: SearchResult[]; errors: ArchiveErr[] };

export default function TargetSearch({ autoFocus = false }: { autoFocus?: boolean }) {
  const router = useRouter();
  const id = useId();
  const [q, setQ] = useState("");
  const [res, setRes] = useState<SearchResult[]>([]);
  const [errors, setErrors] = useState<ArchiveErr[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [fatal, setFatal] = useState<string | null>(null);
  const [searched, setSearched] = useState("");
  const seq = useRef(0);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setRes([]); setErrors([]); setSearched(""); setFatal(null);
      return;
    }
    const mine = ++seq.current;
    const t = setTimeout(async () => {
      setLoading(true);
      setFatal(null);
      try {
        const r = await get<Resp>(`/api/targets/search?q=${encodeURIComponent(term)}`);
        if (mine !== seq.current) return;      // ignore stale responses
        setRes(r.results); setErrors(r.errors); setSearched(term); setOpen(true); setActive(-1);
      } catch (e) {
        if (mine === seq.current) setFatal(e instanceof ApiError ? e.message : "Search failed");
      } finally {
        if (mine === seq.current) setLoading(false);
      }
    }, 350);
    return () => clearTimeout(t);
  }, [q]);

  const go = (r: SearchResult) => router.push(`/targets/detail?key=${encodeURIComponent(r.key)}`);

  return (
    <div className="search-wrap">
      <label htmlFor={id}>Star or planet name, or identifier (e.g. TIC, TOI, KIC, Kepler-10)</label>
      <input
        id={id} type="search" autoComplete="off" autoFocus={autoFocus} value={q} placeholder="Search a target…"
        role="combobox" aria-expanded={open && res.length > 0} aria-controls={`${id}-list`} aria-autocomplete="list"
        onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, res.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
          else if (e.key === "Enter" && res.length) { e.preventDefault(); go(res[active >= 0 ? active : 0]); }
          else if (e.key === "Escape") setOpen(false);
        }}
      />
      <div aria-live="polite" className="small muted" style={{ minHeight: 20, marginTop: 4 }}>
        {loading ? "Searching archives…" : searched && !res.length && !fatal ? `No catalogue match for “${searched}”.` : ""}
      </div>
      {open && res.length > 0 && (
        <div className="suggest" role="listbox" id={`${id}-list`} aria-label="Matching targets">
          {res.map((r, i) => (
            <button key={r.key} role="option" aria-selected={i === active} onClick={() => go(r)}>
              <b>{r.host}</b>{" "}
              <span className="badge">{r.kind === "resolved_object" ? "position only" : r.kind.includes("candidate") ? "candidates only" : "host star"}</span>
              <div className="small muted">
                {r.planets.length ? `Planets: ${r.planets.join(", ")}` : r.candidates?.length ? `Candidates: ${r.candidates.join(", ")}` : r.note}
                {" · "}{r.source}
              </div>
            </button>
          ))}
        </div>
      )}
      {fatal && <div className="notice error" role="alert">{fatal}</div>}
      {errors.map((e, i) => (
        <div key={i} className="notice warn" role="status">
          {e.source} could not be reached: {e.message}{e.retriable ? " (temporary; try again)" : ""}
        </div>
      ))}
    </div>
  );
}
