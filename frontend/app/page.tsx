"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import Dropzone from "@/components/Dropzone";
import TargetSearch from "@/components/TargetSearch";
import Icon from "@/components/Icon";
import { get } from "@/lib/api";

type Recent = { target_key: string; label: string; kind: string };
type Cfg = { max_upload_mb: number; offline: boolean };

// Well-known real objects, offered only as search suggestions (no results or statistics are implied).
const EXAMPLES = ["Kepler-10", "WASP-18", "TOI-700", "pi Mensae", "HD 209458", "TRAPPIST-1"];

export default function Explore() {
  const [recent, setRecent] = useState<Recent[]>([]);
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [down, setDown] = useState(false);
  useEffect(() => {
    get<Recent[]>("/api/targets/recent").then(setRecent).catch(() => {});
    get<Cfg>("/api/config").then(setCfg).catch(() => setDown(true));
  }, []);

  return (
    <div className="home">
      <section className="home-top">
        <p className="eyebrow">Yatra / Explore</p>
        <h1>Explore exoplanets</h1>
        <p className="muted">Search a star, planet, or catalogue identifier to inspect published parameters and available observations.</p>
        <div className="home-search"><TargetSearch /></div>
      </section>
      {down && <div className="notice error" role="alert">The backend API is not reachable. Start it with <code>uvicorn app.main:app</code> (see the README).</div>}
      {cfg?.offline && <div className="notice warn">The server is in offline mode: archive search is disabled.</div>}

      <div className="grid2 action-grid">
        <section className="card feature-card" aria-labelledby="h-search">
          <div className="feature-icon"><Icon name="search" /></div><h2 id="h-search">Explore a target</h2>
          <p className="muted small">Published planets, candidates, host-star facts and available observations in one view.</p>
          <h4>Try a target</h4>
          <div className="row">
            {EXAMPLES.map((e) => <Link key={e} className="btn" href={`/targets?q=${encodeURIComponent(e)}`}>{e}</Link>)}
          </div>
        </section>
        <section className="card feature-card" aria-labelledby="h-up">
          <div className="feature-icon"><Icon name="upload" /></div><h2 id="h-up">Bring your own data</h2>
          <Dropzone maxMb={cfg?.max_upload_mb ?? 50} />
          <p className="small muted" style={{ marginBottom: 0 }}>
            The file type and measurement type are identified automatically and explained; you can correct any column or unit.
          </p>
        </section>
      </div>

      <section className="home-section" aria-labelledby="h-recent">
        <div className="section-heading"><div><p className="eyebrow">Your workspace</p><h2 id="h-recent">Recently explored</h2></div><Link className="text-link" href="/targets">All targets <Icon name="arrow" size={15} /></Link></div>
        {recent.length ? (
          <div className="row">
            {recent.map((r) => <Link key={r.target_key} className="btn" href={`/targets/detail?key=${encodeURIComponent(r.target_key)}`}>{r.label}</Link>)}
          </div>
        ) : <p className="muted small">None yet. Targets you open will appear here.</p>}
      </section>

    </div>
  );
}
