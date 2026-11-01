/** Thin typed client. All calls go to the same-origin /api proxy (see next.config.mjs). */
export class ApiError extends Error {
  status: number;
  hint?: string | null;
  constructor(status: number, message: string, hint?: string | null) {
    super(message);
    this.status = status;
    this.hint = hint;
  }
}

async function parse<T>(r: Response): Promise<T> {
  if (r.ok) return (await r.json()) as T;
  let msg = `Request failed (${r.status})`;
  let hint: string | null | undefined;
  try {
    const b = await r.json();
    msg = b.message || b.detail || b.error || msg;
    hint = b.hint;
    if (typeof msg !== "string") msg = JSON.stringify(msg);
  } catch {
    /* non-JSON error body */
  }
  throw new ApiError(r.status, msg, hint);
}

export const get = <T,>(url: string) => fetch(url, { cache: "no-store" }).then((r) => parse<T>(r));

export const post = <T,>(url: string, body: unknown) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) =>
    parse<T>(r),
  );

export const upload = <T,>(file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return fetch("/api/datasets/upload", { method: "POST", body: fd }).then((r) => parse<T>(r));
};

export const fmt = (v: number | null | undefined, digits = 5) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : String(parseFloat(Number(v).toPrecision(digits)));

export const when = (ts: number | null | undefined) => (ts ? new Date(ts * 1000).toLocaleString() : "—");
