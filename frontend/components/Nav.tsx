"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import Icon from "@/components/Icon";

const LINKS = [
  { href: "/", label: "Explore", icon: "orbit" as const },
  { href: "/targets", label: "Targets", icon: "search" as const },
  { href: "/upload", label: "Upload data", icon: "upload" as const },
  { href: "/analyses", label: "Analyses", icon: "analyses" as const },
  { href: "/docs", label: "Guide", icon: "book" as const },
];

export default function Nav({ appName }: { appName: string }) {
  const path = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <aside className={`nav ${collapsed ? "collapsed" : ""}`} aria-label="Primary navigation">
      <button className="nav-toggle" type="button" onClick={() => setCollapsed((value) => !value)} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} title={collapsed ? "Expand sidebar" : "Collapse sidebar"}><Icon name="panel" size={17} /></button>
      <Link href="/" className="brand"><span className="brand-mark"><Icon name="orbit" size={22} /></span><span>{appName}</span></Link>
      <nav aria-label="Main">
        <p className="nav-label">Workspace</p>
        {LINKS.map((l) => <Link key={l.href} href={l.href} className="link" aria-current={active(l.href) ? "page" : undefined}><Icon name={l.icon} /><span>{l.label}</span></Link>)}
      </nav>
      <div className="nav-bottom"><span className="status-dot" />Live archive data</div>
    </aside>
  );
}
