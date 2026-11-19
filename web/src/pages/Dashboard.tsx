import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, BookOpen, Boxes, FileUp, Search, Star, X } from "lucide-react";
import { ApiError, listTools } from "../api";
import { categoryMeta, CATEGORY_ORDER } from "../categories";
import ToolCard from "../components/ToolCard";
import { CardGridSkeleton } from "../components/Skeleton";
import { PREFS_EVENT, getFavorites, getRecentTools } from "../prefs";
import { fileToolMode, matchesSearch, toolSearchText } from "../toolDiscovery";
import type { ToolInfo } from "../types";

const commonTasks = [
  "pdf-organize", "video-target-size", "subtitle-cleanup", "pdf-merge", "transcribe", "image-convert",
];
const grid = "grid gap-3 sm:grid-cols-2 xl:grid-cols-3";

export default function Dashboard() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("browse");
  const [files, setFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [favorites, setFavorites] = useState(getFavorites);
  const [recents, setRecents] = useState(getRecentTools);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    listTools()
      .then((all) => { if (active) setTools(all); })
      .catch((err: unknown) => {
        if (active) setError(err instanceof ApiError ? err.detail : "Could not load tools.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [attempt]);

  useEffect(() => {
    const sync = () => {
      setFavorites(getFavorites());
      setRecents(getRecentTools());
    };
    window.addEventListener(PREFS_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(PREFS_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const bySlug = useMemo(() => new Map(tools.map((tool) => [tool.slug, tool])), [tools]);
  const frequent = commonTasks.map((slug) => bySlug.get(slug)).filter((tool) => tool?.available);
  const recent = recents.map((slug) => bySlug.get(slug)).filter(Boolean).slice(0, 4);
  const matches = useMemo(() => tools.flatMap((tool) => {
    const mode = fileToolMode(tool, files);
    return mode ? [{ tool, mode }] : [];
  }).sort((a, b) =>
    Number(a.tool.accepts.length === 0) - Number(b.tool.accepts.length === 0)
      || a.tool.name.localeCompare(b.tool.name),
  ), [tools, files]);

  const isBrowsing = category === "browse" && !query.trim();
  const visible = tools.filter((tool) => {
    if (category === "saved" && !favorites.includes(tool.slug)) return false;
    if (!["browse", "all", "saved"].includes(category) && tool.category !== category) return false;
    return matchesSearch(toolSearchText(tool), query);
  }).sort((a, b) => Number(b.available) - Number(a.available) || a.name.localeCompare(b.name));
  const knownCategories = new Set(tools.map((tool) => tool.category));
  const categories = [
    ...CATEGORY_ORDER.filter((key) => knownCategories.has(key)),
    ...[...knownCategories].filter((key) => !CATEGORY_ORDER.includes(key)).sort(),
  ];
  const filters = [
    { key: "all", label: "All tools" },
    ...categories.map(categoryMeta),
    { key: "saved", label: "Saved", icon: Star },
  ];

  return (
    <div className="mx-auto max-w-[74rem] space-y-7">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[clamp(1.85rem,3.3vw,3.15rem)] leading-[1.06] font-bold tracking-[-0.055em] text-fg">Tools</h1>
          <p className="mt-2 text-sm leading-relaxed text-muted sm:text-base">Find a tool or start with the files you want to work on.</p>
        </div>
        <Link to="/recipes" className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line bg-surface px-3 text-sm font-semibold text-fg hover:bg-surface-2">
          <BookOpen aria-hidden="true" className="size-4" /> Browse recipes
        </Link>
      </header>
      <section aria-label="Find tools" className="grid gap-3 md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="rounded-2xl border border-line bg-surface px-4 py-5 sm:p-6">
          <label htmlFor="tool-query" className="font-semibold text-fg">Search the tool library</label>
          <div className="relative mt-2">
            <Search aria-hidden="true" className="pointer-events-none absolute top-3.5 left-3.5 size-4.5 text-muted" />
            <input
              id="tool-query"
              type="search"
              aria-label="Search tools"
              placeholder="Try “make PDF smaller”"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="w-full rounded-lg border border-line bg-surface-2 py-3 pr-4 pl-11 text-sm text-fg placeholder:text-muted"
            />
          </div>
        </div>
        <div
          onDragOver={(event) => { event.preventDefault(); setDragOver(true); }}
          onDragLeave={(event) => {
            if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) {
              setDragOver(false);
            }
          }}
          onDrop={(event) => {
            event.preventDefault();
            setDragOver(false);
            if (event.dataTransfer.files.length) setFiles(Array.from(event.dataTransfer.files));
          }}
          className={`flex flex-wrap items-center justify-between gap-3 rounded-2xl border px-4 py-5 sm:p-6 ${dragOver ? "border-primary bg-primary-soft" : "border-line bg-primary-soft"}`}
        >
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            onChange={(event) => {
              if (event.target.files?.length) setFiles(Array.from(event.target.files));
              event.target.value = "";
            }}
          />
          <div>
            <p className="font-semibold text-fg">Start with files</p>
            <p className="mt-0.5 text-sm text-muted">Drop files here to see what you can do.</p>
          </div>
          <button type="button" onClick={() => inputRef.current?.click()}
            className="inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3 text-sm font-semibold text-primary-fg transition-opacity hover:opacity-90">
            <FileUp aria-hidden="true" className="size-4" />
            {files.length > 0 ? "Choose different files" : "Choose files"}
          </button>
        </div>
      </section>

      {files.length > 0 && (
        <section aria-labelledby="file-tools" className="rounded-xl border border-line bg-surface p-4 sm:p-5">
          <div className="mb-3 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 id="file-tools" className="font-semibold text-fg">Tools for your files</h2>
              <p className="mt-1 text-sm text-muted [overflow-wrap:anywhere]">
                {files.length === 1 ? files[0].name : `${files.length} selected files`}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setFiles([])}
              className="inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-lg px-2 text-sm text-muted hover:bg-surface-2 hover:text-fg"
            >
              <X aria-hidden className="size-4" /> Clear files
            </button>
          </div>
          {loading && <p role="status" className="text-sm text-muted">Checking compatible tools…</p>}
          {!loading && !error && matches.length === 0 && (
            <p role="status" className="text-sm text-muted">
              No tool can use this selection. Try choosing files of the same type or one file at a time.
            </p>
          )}
          {matches.length > 0 && (
            <div className={grid}>
              {matches.map(({ tool, mode }) => (
                <button
                  type="button"
                  key={tool.slug}
                  onClick={() => navigate(mode === "batch" ? "/batch" : `/tool/${tool.slug}`, {
                    state: { presetFiles: files, presetSlug: tool.slug },
                  })}
                  className="flex items-center justify-between gap-2 rounded-lg border border-line px-3 py-2.5 text-left text-sm hover:border-primary hover:bg-surface-2"
                >
                  <span>
                    <span className="block font-medium">{tool.name}</span>
                    {mode === "batch" && <span className="block text-xs text-muted">Run on each file</span>}
                  </span>
                  <ArrowRight aria-hidden className="size-4 shrink-0 text-muted" />
                </button>
              ))}
            </div>
          )}
        </section>
      )}

      <section aria-label="Browse tools">
        <div role="group" aria-label="Filter tools" className="flex flex-wrap gap-2">
          {filters.map(({ key, label, ...meta }) => {
            const Icon = "icon" in meta ? meta.icon : undefined;
            return (
              <button
                type="button"
                key={key}
                aria-pressed={category === key}
                onClick={() => setCategory(category === key ? "browse" : key)}
                className={`inline-flex min-h-10 items-center gap-1.5 rounded-lg border px-3 text-sm font-semibold transition-colors ${category === key ? "border-primary bg-primary text-primary-fg" : "border-line bg-surface text-muted hover:border-primary hover:text-fg"}`}
              >
                {Icon && <Icon aria-hidden className="size-4" />}
                {label}
              </button>
            );
          })}
        </div>
        {loading && <div className="mt-5"><CardGridSkeleton count={6} /></div>}
        {error && (
          <div role="status" className="mt-5 flex flex-wrap items-center gap-3 text-sm">
            <p className="text-danger">{error}</p>
            <button type="button" onClick={() => setAttempt((value) => value + 1)} className="font-medium text-primary underline">
              Try again
            </button>
          </div>
        )}
        {!loading && !error && !isBrowsing && (
          visible.length > 0
            ? (
              <div className="mt-6">
                <h2 className="mb-3 text-lg font-semibold tracking-tight">{query.trim() ? "Matching tools" : filters.find((filter) => filter.key === category)?.label}</h2>
                <div className={grid}>{visible.map((tool) => <ToolCard key={tool.slug} tool={tool} />)}</div>
              </div>
            )
            : <p role="status" className="mt-5 text-sm text-muted">
                {category === "saved" && !query ? "Star a tool to save it here." : "No tools match your search."}
              </p>
        )}
      </section>

      {isBrowsing && frequent.length > 0 && (
        <section aria-labelledby="common-tasks">
          <h2 id="common-tasks" className="mb-3 text-lg font-semibold tracking-tight">Suggested tools</h2>
          <div className={grid}>
            {frequent.map((tool) => tool && <ToolCard key={tool.slug} tool={tool} />)}
          </div>
        </section>
      )}

      {isBrowsing && recent.length > 0 && (
        <section aria-labelledby="recent-tools">
          <h2 id="recent-tools" className="mb-3 text-lg font-semibold tracking-tight">Recently opened</h2>
          <div className="flex flex-wrap gap-2">
            {recent.map((tool) => tool && (
              <Link key={tool.slug} to={`/tool/${tool.slug}`} className="rounded-lg border border-line bg-surface px-3 py-2 text-sm hover:border-primary">
                {tool.name}
              </Link>
            ))}
          </div>
        </section>
      )}

      <Link to="/quick-tools" className="inline-flex items-center gap-2 text-sm font-medium text-muted hover:text-fg">
        <Boxes aria-hidden className="size-4" /> Quick tools <ArrowRight aria-hidden className="size-4" />
      </Link>
    </div>
  );
}
