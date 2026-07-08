import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Boxes, Clock, Search, Sparkles, Star, Upload, X } from "lucide-react";
import { ApiError, listTools } from "../api";
import { accentVar, categoryMeta, CATEGORY_ORDER } from "../categories";
import ToolCard from "../components/ToolCard";
import { CardGridSkeleton } from "../components/Skeleton";
import { PREFS_EVENT, getFavorites, getRecentTools } from "../prefs";
import type { ToolInfo } from "../types";

function extsOf(files: File[]): string[] {
  const set = new Set<string>();
  for (const f of files) {
    const parts = f.name.split(".");
    if (parts.length > 1) set.add("." + parts.pop()!.toLowerCase());
  }
  return [...set];
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [drop, setDrop] = useState<{ files: File[]; matches: ToolInfo[] } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [favSlugs, setFavSlugs] = useState<string[]>(() => getFavorites());
  const [recentSlugs, setRecentSlugs] = useState<string[]>(() => getRecentTools());
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    listTools()
      .then((t) => !cancelled && setTools(t))
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.detail : "Failed to load tools"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  // Keep favorites/recents in sync as they change (starred here or on a tool page).
  useEffect(() => {
    const sync = () => {
      setFavSlugs(getFavorites());
      setRecentSlugs(getRecentTools());
    };
    window.addEventListener(PREFS_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(PREFS_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const bySlug = useMemo(() => new Map(tools.map((t) => [t.slug, t])), [tools]);
  const favTools = useMemo(
    () => favSlugs.map((s) => bySlug.get(s)).filter((t): t is ToolInfo => t !== undefined),
    [favSlugs, bySlug],
  );
  const recentTools = useMemo(
    () =>
      recentSlugs
        .filter((s) => !favSlugs.includes(s))
        .map((s) => bySlug.get(s))
        .filter((t): t is ToolInfo => t !== undefined)
        .slice(0, 4),
    [recentSlugs, favSlugs, bySlug],
  );

  const suggest = (files: File[]) => {
    if (!files.length) return;
    const exts = extsOf(files);
    const byExt = tools.filter(
      (t) => t.available && t.min_files > 0 && t.accepts.length > 0 &&
        t.accepts.some((a) => exts.includes(a.toLowerCase())),
    );
    const anyFile = tools.filter((t) => t.available && t.min_files > 0 && t.accepts.length === 0);
    setDrop({ files, matches: [...byExt, ...anyFile] });
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files.length) suggest(Array.from(e.dataTransfer.files));
  };

  const openTool = (slug: string) =>
    navigate(`/tool/${slug}`, { state: drop ? { presetFiles: drop.files } : undefined });

  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? tools.filter((t) => t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q))
      : tools;
    const byCat = new Map<string, ToolInfo[]>();
    for (const t of filtered) {
      const list = byCat.get(t.category) ?? [];
      list.push(t);
      byCat.set(t.category, list);
    }
    const cats = [
      ...CATEGORY_ORDER.filter((c) => byCat.has(c)),
      ...[...byCat.keys()].filter((c) => !CATEGORY_ORDER.includes(c)).sort(),
    ];
    return cats.map((c) => ({ category: c, tools: byCat.get(c)!.slice().sort((a, b) => a.name.localeCompare(b.name)) }));
  }, [tools, query]);

  const available = tools.filter((t) => t.available).length;

  return (
    <div>
      {/* Hero + smart drop zone */}
      <section className="mb-6 overflow-hidden rounded-3xl border border-line bg-surface p-6 sm:p-8">
        <div className="mb-5 flex flex-col gap-1">
          <h1 className="text-2xl font-bold tracking-tight text-fg sm:text-3xl">Your private toolbox</h1>
          <p className="text-muted">
            {loading ? "Loading tools…" : `${available} tools for PDFs, images, media, documents & AI — running locally.`}
          </p>
        </div>
        <div
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed p-8 text-center transition-colors"
          style={{
            borderColor: dragOver ? accentVar("quick") : "var(--color-line)",
            background: dragOver ? "color-mix(in srgb, var(--color-primary) 8%, transparent)" : "var(--color-surface-2)",
          }}
        >
          <span className="grid h-12 w-12 place-items-center rounded-2xl bg-primary-soft">
            <Upload className="h-6 w-6 text-primary" />
          </span>
          <p className="font-medium text-fg">Drop a file to see what you can do</p>
          <p className="text-sm text-muted">or click to browse — we&apos;ll suggest the right tools</p>
          <input
            ref={inputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              if (e.target.files) suggest(Array.from(e.target.files));
              e.target.value = "";
            }}
          />
        </div>
      </section>

      {/* Suggestions */}
      {drop && (
        <section className="animate-in mb-8 rounded-2xl border border-line bg-surface p-4 shadow-[var(--shadow-card)]">
          <div className="mb-3 flex items-center justify-between gap-2">
            <p className="flex items-center gap-2 text-sm text-fg">
              <Sparkles className="h-4 w-4 text-primary" />
              For <span className="font-semibold">{drop.files.map((f) => f.name).join(", ")}</span> you can:
            </p>
            <button onClick={() => setDrop(null)} className="grid h-7 w-7 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-fg">
              <X className="h-4 w-4" />
            </button>
          </div>
          {drop.matches.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted">No tools match that file type.</p>
          ) : (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {drop.matches.map((t) => {
                const meta = categoryMeta(t.category);
                const Icon = meta.icon;
                return (
                  <button
                    key={t.slug}
                    onClick={() => openTool(t.slug)}
                    className="flex items-center gap-3 rounded-xl border border-line bg-surface-2 p-3 text-left transition-colors hover:border-primary"
                  >
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg" style={{ background: `color-mix(in srgb, ${accentVar(meta.accent)} 14%, transparent)` }}>
                      <Icon className="h-4.5 w-4.5" style={{ color: accentVar(meta.accent) }} />
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-fg">{t.name}</span>
                      <span className="block truncate text-xs text-muted">{t.description}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </section>
      )}

      {/* Favorites & recents */}
      {!query && favTools.length > 0 && (
        <section className="mb-8">
          <div className="mb-3 flex items-center gap-2.5">
            <span className="grid h-8 w-8 place-items-center rounded-lg" style={{ background: `color-mix(in srgb, ${accentVar("img")} 14%, transparent)` }}>
              <Star className="h-4.5 w-4.5" style={{ color: accentVar("img") }} fill="currentColor" />
            </span>
            <h3 className="font-semibold text-fg">Favorites</h3>
            <span className="text-sm text-faint">{favTools.length}</span>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {favTools.map((t) => (
              <ToolCard key={t.slug} tool={t} />
            ))}
          </div>
        </section>
      )}

      {!query && recentTools.length > 0 && (
        <section className="mb-8">
          <div className="mb-3 flex items-center gap-2.5">
            <span className="grid h-8 w-8 place-items-center rounded-lg" style={{ background: `color-mix(in srgb, ${accentVar("util")} 14%, transparent)` }}>
              <Clock className="h-4.5 w-4.5" style={{ color: accentVar("util") }} />
            </span>
            <h3 className="font-semibold text-fg">Recent</h3>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {recentTools.map((t) => (
              <ToolCard key={t.slug} tool={t} />
            ))}
          </div>
        </section>
      )}

      {/* Search */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-fg">All tools</h2>
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-faint" />
          <input
            type="search"
            placeholder="Search tools…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full rounded-full border border-line bg-surface py-2 pl-9 pr-3 text-sm text-fg outline-none transition-colors placeholder:text-faint focus:border-primary"
          />
        </div>
      </div>

      {error && (
        <p className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-danger">{error}</p>
      )}
      {loading && <CardGridSkeleton count={12} />}
      {!loading && !error && grouped.length === 0 && (
        <p className="text-sm text-muted">No tools match your search.</p>
      )}

      {grouped.map(({ category, tools: catTools }) => {
        const meta = categoryMeta(category);
        const Icon = meta.icon;
        return (
          <section key={category} className="mb-8">
            <div className="mb-3 flex items-center gap-2.5">
              <span className="grid h-8 w-8 place-items-center rounded-lg" style={{ background: `color-mix(in srgb, ${accentVar(meta.accent)} 14%, transparent)` }}>
                <Icon className="h-4.5 w-4.5" style={{ color: accentVar(meta.accent) }} />
              </span>
              <h3 className="font-semibold text-fg">{meta.label}</h3>
              <span className="text-sm text-faint">{catTools.length}</span>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {catTools.map((t) => (
                <ToolCard key={t.slug} tool={t} />
              ))}
            </div>
          </section>
        );
      })}

      {/* Quick tools teaser */}
      <button
        onClick={() => navigate("/quick-tools")}
        className="flex w-full items-center gap-4 rounded-2xl border border-line bg-surface p-5 text-left shadow-[var(--shadow-card)] transition-all hover:-translate-y-0.5 hover:shadow-[var(--shadow-pop)]"
      >
        <span className="grid h-11 w-11 place-items-center rounded-xl" style={{ background: `color-mix(in srgb, ${accentVar("quick")} 14%, transparent)` }}>
          <Boxes className="h-5 w-5" style={{ color: accentVar("quick") }} />
        </span>
        <span>
          <span className="block font-semibold text-fg">Quick Tools</span>
          <span className="block text-sm text-muted">Hundreds of instant in-browser utilities — encoders, converters, formatters & more.</span>
        </span>
      </button>
    </div>
  );
}
