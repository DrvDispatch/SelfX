import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, Boxes, Clipboard, Layers, LayoutGrid, ListChecks, Search, Sparkles, Workflow, type LucideIcon } from "lucide-react";
import { listTools } from "../api";
import { accentVar, categoryMeta } from "../categories";
import type { ToolInfo } from "../types";

interface Item {
  id: string;
  label: string;
  sub?: string;
  to: string;
  icon: LucideIcon;
  accent?: string;
}

const PAGES: Item[] = [
  { id: "p-home", label: "Dashboard", sub: "All tools", to: "/", icon: LayoutGrid, accent: "quick" },
  { id: "p-assistant", label: "Assistant", sub: "Ask in natural language", to: "/assistant", icon: Sparkles, accent: "ai" },
  { id: "p-kb", label: "Knowledge", sub: "Chat with your documents", to: "/knowledge", icon: BookOpen, accent: "docs" },
  { id: "p-paste", label: "Paste image", sub: "Paste a screenshot to save or edit", to: "/paste", icon: Clipboard, accent: "img" },
  { id: "p-batch", label: "Batch", sub: "Run one tool over many files", to: "/batch", icon: Layers, accent: "util" },
  { id: "p-pipeline", label: "Pipeline", sub: "Chain tools together", to: "/pipeline", icon: Workflow, accent: "ai" },
  { id: "p-jobs", label: "Jobs", sub: "History & downloads", to: "/jobs", icon: ListChecks, accent: "util" },
  { id: "p-quick", label: "Quick Tools", sub: "In-browser utilities", to: "/quick-tools", icon: Boxes, accent: "quick" },
  { id: "p-models", label: "AI Models", sub: "Manage Ollama models", to: "/models", icon: Boxes, accent: "media" },
];

export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    if (open && tools.length === 0) listTools().then(setTools).catch(() => undefined);
  }, [open, tools.length]);
  useEffect(() => {
    if (open) { setQ(""); setIdx(0); }
  }, [open]);

  const items = useMemo(() => {
    const toolItems: Item[] = tools.map((t) => {
      const m = categoryMeta(t.category);
      return { id: "t-" + t.slug, label: t.name, sub: t.description, to: "/tool/" + t.slug, icon: m.icon, accent: m.accent };
    });
    const all = [...PAGES, ...toolItems];
    const query = q.trim().toLowerCase();
    if (!query) return all.slice(0, 60);
    return all.filter((i) => i.label.toLowerCase().includes(query) || (i.sub ?? "").toLowerCase().includes(query)).slice(0, 60);
  }, [tools, q]);

  useEffect(() => {
    if (idx >= items.length) setIdx(0);
  }, [items.length, idx]);

  if (!open) return null;

  const go = (it: Item) => { onClose(); navigate(it.to); };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); if (items[idx]) go(items[idx]); }
    else if (e.key === "Escape") { onClose(); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-[12vh] backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-lg overflow-hidden rounded-2xl border border-line bg-surface shadow-[var(--shadow-pop)]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-line px-3">
          <Search className="h-4 w-4 text-faint" />
          <input
            autoFocus
            value={q}
            onChange={(e) => { setQ(e.target.value); setIdx(0); }}
            onKeyDown={onKey}
            placeholder="Search tools & pages…"
            className="w-full bg-transparent py-3 text-sm text-fg outline-none placeholder:text-faint"
          />
          <kbd className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-faint">esc</kbd>
        </div>
        <div className="max-h-80 overflow-y-auto p-1.5">
          {items.length === 0 && <p className="p-4 text-center text-sm text-muted">No matches.</p>}
          {items.map((it, i) => {
            const Icon = it.icon;
            return (
              <button
                key={it.id}
                onMouseMove={() => setIdx(i)}
                onClick={() => go(it)}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors ${i === idx ? "bg-primary-soft" : ""}`}
              >
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg" style={{ background: `color-mix(in srgb, ${accentVar(it.accent ?? "quick")} 14%, transparent)` }}>
                  <Icon className="h-4 w-4" style={{ color: accentVar(it.accent ?? "quick") }} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-fg">{it.label}</span>
                  {it.sub && <span className="block truncate text-xs text-muted">{it.sub}</span>}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
