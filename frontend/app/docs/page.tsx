import type { Metadata } from "next";
import Icon from "@/components/Icon";

export const metadata: Metadata = { title: "Guide" };

const STATUS: [string, string, string][] = [
  ["Transit photometry", "available", "Cleaning, detrending, BLS search, vetting, model fit and exports for TESS, Kepler and uploaded light curves."],
  ["Radial velocity", "planned", "Recognised and described; no periodogram or orbit fit yet."],
  ["Spectroscopy / atmospheres", "planned", "Spectra are recognised; no atmospheric retrieval yet."],
  ["Direct imaging", "planned", "Image FITS files are recognised; no PSF subtraction yet."],
  ["Astrometry / microlensing", "planned", "No orbit fitting or microlensing detection yet."],
];

export default function Docs() {
  return (
    <div className="guide-page">
      <header className="guide-intro">
        <p className="eyebrow">Yatra guide</p>
        <h1>Start exploring</h1>
        <p className="muted">Use Yatra to find a system, inspect what the catalogues report, and analyse a light curve when one is available.</p>
      </header>

      <section aria-labelledby="quick-start">
        <h2 id="quick-start">Quick start</h2>
        <div className="guide-steps">
          <article className="guide-step"><span className="step-number">01</span><div><h3>Find a target</h3><p>Search by planet or star name, or a TIC, TOI, KIC or KOI identifier.</p></div><Icon name="search" /></article>
          <article className="guide-step"><span className="step-number">02</span><div><h3>Read the record</h3><p>Review the host star, confirmed planets, candidates and values labelled as local ML estimates.</p></div><Icon name="orbit" /></article>
          <article className="guide-step"><span className="step-number">03</span><div><h3>Open observations</h3><p>Choose an available TESS, Kepler or K2 light-curve product, then load and inspect it.</p></div><Icon name="database" /></article>
          <article className="guide-step"><span className="step-number">04</span><div><h3>Analyse or export</h3><p>Run a transit analysis, inspect candidates and diagnostics, then export the result.</p></div><Icon name="analyses" /></article>
        </div>
      </section>

      <section className="guide-callout" aria-labelledby="graphs-guide">
        <p className="eyebrow">Reading target pages</p>
        <h2 id="graphs-guide">What the graphs show</h2>
        <div className="guide-grid">
          <div><h3>Radius vs revolution period</h3><p>Each point is a planet or catalogue candidate. The horizontal axis is the time it takes to orbit its star; the vertical axis is its radius in Earth radii. Both axes use a logarithmic scale, so compare broad trends rather than visual distance alone.</p></div>
          <div><h3>Observation coverage</h3><p>Each bar marks the dates covered by a TESS, Kepler or K2 observation. Dark bars can be loaded for transit analysis; grey bars are listed for context but are not supported here.</p></div>
        </div>
      </section>

      <section className="technical-guide" aria-labelledby="technical">
        <p className="eyebrow">Reference</p>
        <h2 id="technical">Technical details</h2>
        <h3>Available methods</h3>
        <div className="table-wrap"><table>
          <thead><tr><th>Technique</th><th>Status</th><th>Notes</th></tr></thead>
          <tbody>{STATUS.map(([a, b, c]) => <tr key={a}><td>{a}</td><td><span className={`badge ${b}`}>{b}</span></td><td className="small">{c}</td></tr>)}</tbody>
        </table></div>
        <h3>Transit analysis</h3>
        <ol>
          <li><b>Cleaning.</b> Non-finite values, flagged cadences and isolated outliers are removed while multi-cadence dips are retained.</li>
          <li><b>Detrending.</b> A running median removes slow variability. A second pass masks detected transits before the trend is re-estimated.</li>
          <li><b>Search.</b> Astropy Box Least Squares searches a period grid with physically limited transit durations and can extract several candidates.</li>
          <li><b>Vetting and fit.</b> The app checks significance, odd/even depth, secondary eclipses and aliases, then fits a limb-darkened transit model.</li>
        </ol>
        <h3>Data sources</h3>
        <div className="table-wrap"><table>
          <thead><tr><th>Source</th><th>Used for</th></tr></thead>
          <tbody>
            <tr><td><a href="https://exoplanetarchive.ipac.caltech.edu">NASA Exoplanet Archive</a></td><td>Published planets, stellar parameters, TESS Objects of Interest and Kepler KOIs</td></tr>
            <tr><td><a href="https://mast.stsci.edu">MAST</a></td><td>Name resolution plus TESS, Kepler and K2 observations and light-curve files</td></tr>
            <tr><td><a href="https://exo.mast.stsci.edu">Exo.MAST</a></td><td>Additional identifier resolution and aliases</td></tr>
          </tbody>
        </table></div>
        <h3>Scientific limits</h3>
        <ul>
          <li>Published planets, candidates, detected signals and validated planets are separate. A signal found in Yatra is never called confirmed.</li>
          <li>Values marked <span className="badge estimate">ML estimate</span> are local model approximations. They are not measurements, detections or confirmation.</li>
          <li>Vetting cannot replace centroid analysis, follow-up photometry or spectroscopy. Fit uncertainties assume white noise and may be optimistic for real data.</li>
        </ul>
      </section>
    </div>
  );
}
