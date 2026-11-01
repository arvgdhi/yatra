"use client";
import { useEffect, useId, useRef, useState } from "react";
import { useColors } from "./Plot";

export type WirePlanet = { name: string; radius: number | null; err?: number | null; note?: string };

const EARTH_KM = 6371;

/**
 * Wireframe globe drawn on a canvas (no 3D library). Sphere radius is strictly proportional to the planet's radius in Earth radii,
 * drawn beside an Earth-sized reference sphere at the same scale (the zoom adapts to the selected planet). It shows size only: the surface, atmosphere and
 * composition are unknown and are not depicted.
 */
export default function PlanetWireframe({ planets, height = 300 }: { planets: WirePlanet[]; height?: number }) {
  const col = useColors();
  const ref = useRef<HTMLCanvasElement>(null);
  const id = useId();
  const withR = planets.filter((p) => p.radius != null && p.radius > 0);
  const [sel, setSel] = useState(0);
  const cur = withR[Math.min(sel, Math.max(withR.length - 1, 0))];
  // Scale is set so the larger of {this planet, Earth} fills the frame; the Earth sphere is always drawn at the same scale, so the
  // two spheres' relative sizes are exact.
  const maxR = Math.max(1, cur?.radius ?? 1);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !cur) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0, yaw = 0.6, visible = true;

    const fit = () => {
      const w = canvas.clientWidth;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(height * dpr);
    };
    fit();
    const ro = new ResizeObserver(() => { fit(); draw(); });
    ro.observe(canvas);
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; }, { threshold: 0 });
    io.observe(canvas);

    function sphere(cx: number, cy: number, R: number, color: string, rot: number, dashed = false) {
      const c = ctx!;
      const tilt = 0.45;
      const st = Math.sin(tilt), ct = Math.cos(tilt);
      const proj = (lat: number, lon: number) => {
        let x = Math.cos(lat) * Math.cos(lon + rot), y = Math.sin(lat), z = Math.cos(lat) * Math.sin(lon + rot);
        const y2 = y * ct - z * st, z2 = y * st + z * ct;
        return [cx + x * R, cy - y2 * R, z2] as const;
      };
      c.lineWidth = Math.max(0.8, dpr * 0.9);
      c.strokeStyle = color;
      c.setLineDash(dashed ? [4 * dpr, 4 * dpr] : []);
      const line = (f: (t: number) => [number, number]) => {
        const N = 72;
        let prev = proj(...f(0));
        for (let i = 1; i <= N; i++) {
          const p = proj(...f(i / N));
          c.globalAlpha = (prev[2] + p[2]) / 2 >= 0 ? 0.95 : 0.2;
          c.beginPath(); c.moveTo(prev[0], prev[1]); c.lineTo(p[0], p[1]); c.stroke();
          prev = p;
        }
      };
      for (let k = -60; k <= 60; k += 30) line((t) => [(k * Math.PI) / 180, t * 2 * Math.PI]);          // parallels
      for (let k = 0; k < 12; k++) line((t) => [(t - 0.5) * Math.PI, (k * Math.PI) / 6]);               // meridians
      c.globalAlpha = 1;
      c.beginPath(); c.arc(cx, cy, R, 0, 2 * Math.PI); c.stroke();                                          // limb
      c.setLineDash([]);
    }

    function draw() {
      const c = ctx!;
      const W = canvas!.width, H = canvas!.height;
      c.clearRect(0, 0, W, H);
      const pad = 28 * dpr;
      const Rmax = Math.min(H / 2 - pad, W * 0.2);
      const scale = Rmax / maxR;                       // px per Earth radius
      const Rp = (cur!.radius as number) * scale;
      const Re = 1 * scale;
      const cyP = H / 2 - 8 * dpr;
      const cxP = W * 0.3, cxE = W * 0.76;
      sphere(cxP, cyP, Rp, col.c1, yaw);
      sphere(cxE, cyP, Re, col.muted, yaw * 0.9, true);
      c.fillStyle = col.text; c.textAlign = "center"; c.font = `${12 * dpr}px ${getComputedStyle(document.body).fontFamily}`;
      c.fillText(cur!.name, cxP, H - 10 * dpr);
      c.fillStyle = col.muted;
      c.fillText("Earth (reference)", cxE, H - 10 * dpr);
    }

    function tick() {
      if (visible) { yaw += 0.006; draw(); }
      raf = requestAnimationFrame(tick);
    }
    draw();
    if (!reduce) raf = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); };
  }, [cur, maxR, col, height]);

  if (!withR.length) {
    return <p className="muted small" style={{ margin: 0 }}>No planet radius is available, so there is nothing to draw to scale. A radius needs a measured planet-to-star radius ratio and a stellar radius.</p>;
  }
  const km = Math.round((cur!.radius as number) * EARTH_KM);
  return (
    <div>
      {withR.length > 1 && (
        <div className="tabs compact" role="tablist" aria-label="Choose planet">
          {withR.map((p, i) => (
            <button key={p.name} role="tab" aria-selected={i === sel} onClick={() => setSel(i)}>{p.name}</button>
          ))}
        </div>
      )}
      <canvas ref={ref} className="wire" style={{ height }} role="img" aria-labelledby={id}
              aria-describedby={`${id}-d`} />
      <span id={id} hidden>Wireframe globe of {cur!.name} next to Earth, drawn to scale by radius</span>
      <p id={`${id}-d`} className="small muted" style={{ margin: "6px 0 0" }}>
        {cur!.name}: <span className="num">{(cur!.radius as number).toFixed(2)} R⊕{cur!.err ? ` ± ${cur!.err.toFixed(2)}` : ""}</span> (≈ {km.toLocaleString()} km).
        Size only to scale: surface and composition are unknown. {cur!.note ?? ""}
      </p>
    </div>
  );
}
