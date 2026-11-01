"use client";
import { useEffect, useState } from "react";
import Dropzone from "@/components/Dropzone";
import { get } from "@/lib/api";

export default function UploadPage() {
  const [max, setMax] = useState(50);
  useEffect(() => { get<{ max_upload_mb: number }>("/api/config").then((c) => setMax(c.max_upload_mb)).catch(() => {}); }, []);
  return (
    <div style={{ maxWidth: 780 }}>
      <h1>Upload data</h1>
      <p className="muted">Upload a light curve. The file is inspected, its measurement type is identified with the evidence shown, and you decide whether to run an analysis.</p>
      <Dropzone maxMb={max} />
      <div className="card" style={{ marginTop: 20 }}>
        <h3>What is accepted</h3>
        <ul>
          <li><b>CSV / TSV / TXT tables</b> with time and flux columns. Common names (<code>time</code>, <code>BJD</code>, <code>flux</code>, <code>PDCSAP_FLUX</code>, <code>flux_err</code> …) are recognised; otherwise you map them yourself. Time in days, hours, minutes or seconds; flux as counts, normalised flux or magnitudes.</li>
          <li><b>FITS</b> files with a binary-table extension, including TESS and Kepler SPOC light curves (<code>*_lc.fits</code>, <code>*_llc.fits</code>). Header keywords give the mission and time reference.</li>
          <li>Radial-velocity tables, spectra, images and astrometric tables are <i>recognised</i> and described, but their analysis modules are not implemented yet.</li>
        </ul>
        <h3>Handling</h3>
        <ul>
          <li>Maximum size {max} MB. Files are stored under a random name, parsed only as data, never executed, and deleted automatically after a retention period.</li>
          <li>Your original file is never modified; every analysis works on a copy in memory.</li>
        </ul>
      </div>
    </div>
  );
}
