import type { SVGProps } from "react";

type IconName = "orbit" | "search" | "upload" | "analyses" | "book" | "spark" | "arrow" | "database" | "panel";

const paths: Record<IconName, React.ReactNode> = {
  orbit: <><circle cx="12" cy="12" r="2.5" /><ellipse cx="12" cy="12" rx="9" ry="4.5" transform="rotate(-28 12 12)" /></>,
  search: <><circle cx="10.7" cy="10.7" r="5.7" /><path d="m15 15 4.2 4.2" /></>,
  upload: <><path d="M12 16V4m0 0-4 4m4-4 4 4M5 15v4h14v-4" /></>,
  analyses: <><path d="M5 19V9m7 10V5m7 14v-7" /><path d="M3.5 19.5h17" /></>,
  book: <><path d="M4.5 5.5A2.5 2.5 0 0 1 7 3h4.5v17H7a2.5 2.5 0 0 0-2.5 2.5zM19.5 5.5A2.5 2.5 0 0 0 17 3h-5.5v17H17a2.5 2.5 0 0 1 2.5 2.5z" /></>,
  spark: <path d="m12 3 1.45 5.55L19 10l-5.55 1.45L12 17l-1.45-5.55L5 10l5.55-1.45L12 3Zm6 12 .7 2.3L21 18l-2.3.7L18 21l-.7-2.3L15 18l2.3-.7L18 15Z" />,
  arrow: <><path d="M5 12h13m-5-5 5 5-5 5" /></>,
  database: <><ellipse cx="12" cy="5" rx="7" ry="3" /><path d="M5 5v7c0 1.66 3.13 3 7 3s7-1.34 7-3V5m-14 7v7c0 1.66 3.13 3 7 3s7-1.34 7-3v-7" /></>,
  panel: <><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M10 4v16m4-11-3 3 3 3" /></>,
};

export default function Icon({ name, size = 18, ...props }: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>;
}
