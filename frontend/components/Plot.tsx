"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

const PlotlyChart = dynamic<any>(
  async () => {
    const Plotly = (await import("plotly.js-basic-dist-min")).default;
    const factory = (await import("react-plotly.js/factory")).default;
    return factory(Plotly);
  },
  { ssr: false, loading: () => <div className="empty" role="status">Loading chart…</div> },
);

export type Colors = { text: string; grid: string; c1: string; c2: string; c3: string; muted: string };

function read(): Colors {
  const s = getComputedStyle(document.documentElement);
  const g = (n: string) => s.getPropertyValue(n).trim();
  return { text: g("--text"), grid: g("--plot-grid"), c1: g("--plot-1"), c2: g("--plot-2"), c3: g("--plot-3"), muted: g("--muted") };
}

/** Colours follow the page theme (light/dark) so charts stay legible. */
export function useColors(): Colors {
  const [c, setC] = useState<Colors>({ text: "#141414", grid: "#e4e4df", c1: "#1a1a1a", c2: "#1d4ed8", c3: "#b3261e", muted: "#62625d" });
  useEffect(() => {
    setC(read());
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const h = () => setC(read());
    mq.addEventListener("change", h);
    return () => mq.removeEventListener("change", h);
  }, []);
  return c;
}

type Props = {
  data: any[];
  title: string;       // accessible name, also shown as the chart caption
  xTitle: string;
  yTitle: string;
  height?: number;
  xType?: "linear" | "log" | "date";
  yType?: "linear" | "log" | "category";
  extraLayout?: Record<string, unknown>;
  yRange?: [number, number];
  shapes?: any[];
  caption?: string;
};

export default function Plot({ data, title, xTitle, yTitle, height = 340, xType = "linear", yType = "linear", yRange, shapes, caption, extraLayout }: Props) {
  const c = useColors();
  const axis = (t: string, extra: object = {}) => ({
    title: { text: t, font: { size: 12, color: c.muted } },
    color: c.text, gridcolor: c.grid, zerolinecolor: c.grid, linecolor: c.grid, tickfont: { size: 11 }, ...extra,
  });
  return (
    <figure style={{ margin: 0 }} aria-label={title}>
      <figcaption className="small muted" style={{ marginBottom: 4 }}>{title}</figcaption>
      <PlotlyChart
        className="plot"
        data={data}
        layout={{
          autosize: true, height, margin: { l: 62, r: 14, t: 8, b: 48 },
          paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
          font: { family: "Inter Variable, Inter, ui-sans-serif, system-ui, sans-serif", color: c.text },
          xaxis: axis(xTitle, { type: xType }), yaxis: axis(yTitle, { type: yType, ...(yRange ? { range: yRange } : {}), ...((extraLayout?.yaxis as object) ?? {}) }),
          legend: { orientation: "h", y: 1.12, font: { size: 11 } }, shapes: shapes ?? [], hovermode: "closest", ...Object.fromEntries(Object.entries(extraLayout ?? {}).filter(([k]) => k !== "yaxis")),
        }}
        config={{ responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d"] }}
        useResizeHandler
        style={{ width: "100%" }}
      />
      {caption && <p className="small muted" style={{ marginTop: 2 }}>{caption}</p>}
    </figure>
  );
}
