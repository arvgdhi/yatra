"use client";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { ApiError, upload } from "@/lib/api";
import type { Dataset } from "@/lib/types";

export default function Dropzone({ maxMb = 50 }: { maxMb?: number }) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ message: string; hint?: string | null } | null>(null);

  async function handle(file: File | undefined) {
    if (!file) return;
    setErr(null);
    if (file.size > maxMb * 1024 * 1024) {
      setErr({ message: `${file.name} is ${(file.size / 1e6).toFixed(0)} MB, above the ${maxMb} MB limit.`, hint: "Subset or bin the data first." });
      return;
    }
    setBusy(true);
    try {
      const ds = await upload<Dataset>(file);
      router.push(`/datasets/${ds.id}`);
    } catch (e) {
      setErr(e instanceof ApiError ? { message: e.message, hint: e.hint } : { message: "Upload failed. Is the backend running?" });
      setBusy(false);
    }
  }

  return (
    <div>
      <div
        className={`drop${over ? " over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); handle(e.dataTransfer.files?.[0]); }}
      >
        <p style={{ margin: 0, fontWeight: 600 }}>{busy ? "Uploading and profiling…" : "Drop a data file here"}</p>
        <p className="small muted" style={{ margin: "4px 0 12px" }}>
          CSV, TSV, TXT or FITS (TESS / Kepler light curves). Up to {maxMb} MB. Files are only parsed as data, never executed.
        </p>
        <button className="primary" disabled={busy} onClick={() => input.current?.click()}>Choose file</button>
        <input ref={input} type="file" hidden aria-label="Choose a data file to upload" accept=".csv,.tsv,.txt,.dat,.fits,.fit"
               onChange={(e) => handle(e.target.files?.[0])} />
      </div>
      {err && (
        <div className="notice error" role="alert">
          <b>{err.message}</b>
          {err.hint && <div className="small">{err.hint}</div>}
        </div>
      )}
    </div>
  );
}
