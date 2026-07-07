import { useState } from "react";
import { ExternalLink } from "lucide-react";
import { accentVar } from "../categories";

interface App {
  key: string;
  name: string;
  desc: string;
  url: string;
  accent: string;
}

// Each utility suite is served as a local static site on its own port; we build the
// URL from whatever host the app is opened on so it works over localhost or a LAN IP.
const HOST = typeof window !== "undefined" ? window.location.hostname : "localhost";
const APPS: App[] = [
  { key: "it-tools", name: "IT-Tools", desc: "100+ developer utilities — encoders, converters, generators, crypto, network.", url: `http://${HOST}:8092`, accent: "docs" },
  { key: "cyberchef", name: "CyberChef", desc: "The Cyber Swiss-Army Knife — 300+ chainable operations for data & forensics.", url: `http://${HOST}:8091`, accent: "ai" },
  { key: "omni-tools", name: "Omni-Tools", desc: "Image, video, PDF, list & text utilities, all in your browser.", url: `http://${HOST}:8093`, accent: "img" },
];

export default function QuickTools() {
  const [active, setActive] = useState<App | null>(null);

  if (active) {
    return (
      <div className="flex h-[calc(100vh-7rem)] flex-col">
        <div className="mb-3 flex items-center gap-3">
          <button onClick={() => setActive(null)} className="rounded-full bg-surface-2 px-3 py-1.5 text-sm font-medium text-fg hover:bg-line">
            ← Back
          </button>
          <span className="font-semibold text-fg">{active.name}</span>
          <a href={active.url} target="_blank" rel="noreferrer" className="ml-auto flex items-center gap-1 text-sm text-primary hover:underline">
            Open in new tab <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </div>
        <iframe
          title={active.name}
          src={active.url}
          className="flex-1 rounded-2xl border border-line bg-surface"
        />
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight text-fg">Quick Tools</h1>
        <p className="text-muted">Hundreds of instant, in-browser utilities — nothing leaves your machine.</p>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {APPS.map((app) => (
          <div key={app.key} className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-5 shadow-[var(--shadow-card)]">
            <div className="flex items-center gap-3">
              <span className="grid h-11 w-11 place-items-center rounded-xl text-lg font-bold" style={{ background: `color-mix(in srgb, ${accentVar(app.accent)} 14%, transparent)`, color: accentVar(app.accent) }}>
                {app.name[0]}
              </span>
              <span className="font-semibold text-fg">{app.name}</span>
            </div>
            <p className="text-sm text-muted">{app.desc}</p>
            <div className="mt-auto flex gap-2">
              <button onClick={() => setActive(app)} className="rounded-full bg-primary px-3 py-1.5 text-sm font-medium text-primary-fg hover:opacity-90">
                Open
              </button>
              <a href={app.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 rounded-full bg-surface-2 px-3 py-1.5 text-sm font-medium text-fg hover:bg-line">
                New tab <ExternalLink className="h-3.5 w-3.5" />
              </a>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-6 text-xs text-faint">
        Tip: these run as separate local services. If a tool doesn&apos;t load, its service may still be starting.
      </p>
    </div>
  );
}
