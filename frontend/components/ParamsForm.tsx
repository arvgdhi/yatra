"use client";
import type { ModuleParam } from "@/lib/types";

/** Renders basic parameters up front and advanced ones behind a disclosure. Values are kept as strings
 *  until submission so that empty fields mean "use the default" rather than 0. */
export default function ParamsForm({
  params, values, onChange,
}: { params: ModuleParam[]; values: Record<string, string>; onChange: (v: Record<string, string>) => void }) {
  const field = (p: ModuleParam) => {
    const id = `p-${p.name}`;
    const set = (v: string) => onChange({ ...values, [p.name]: v });
    return (
      <div className="field" key={p.name}>
        <label htmlFor={id}>{p.name}</label>
        {p.type === "choice" ? (
          <select id={id} value={values[p.name] ?? String(p.default)} onChange={(e) => set(e.target.value)}>
            {p.choices?.map((c) => <option key={c}>{c}</option>)}
          </select>
        ) : p.type === "bool" ? (
          <select id={id} value={values[p.name] ?? String(p.default)} onChange={(e) => set(e.target.value)}>
            <option value="true">yes</option><option value="false">no</option>
          </select>
        ) : (
          <input id={id} type="number" step="any" min={p.min ?? undefined} max={p.max ?? undefined}
                 placeholder={p.default === null ? "auto" : String(p.default)} value={values[p.name] ?? ""}
                 onChange={(e) => set(e.target.value)} />
        )}
        <div className="hint">{p.description}</div>
      </div>
    );
  };
  const basic = params.filter((p) => !p.advanced);
  const adv = params.filter((p) => p.advanced);
  return (
    <div>
      <div className="grid2">{basic.map(field)}</div>
      <details>
        <summary>Advanced settings</summary>
        <div className="grid2" style={{ marginTop: 10 }}>{adv.map(field)}</div>
      </details>
    </div>
  );
}

/** Convert form strings to the nested params object the API expects (dotted names become nested). */
export function buildParams(params: ModuleParam[], values: Record<string, string>): Record<string, unknown> {
  const out: Record<string, any> = {};
  for (const p of params) {
    const raw = values[p.name];
    if (raw === undefined || raw === "") continue;
    const v: unknown = p.type === "bool" ? raw === "true" : p.type === "choice" ? raw : p.type === "int" ? parseInt(raw, 10) : parseFloat(raw);
    if (typeof v === "number" && Number.isNaN(v)) continue;
    const parts = p.name.split(".");
    let o = out;
    parts.slice(0, -1).forEach((k) => (o = o[k] ??= {}));
    o[parts[parts.length - 1]] = v;
  }
  return out;
}
