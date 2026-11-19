import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Star } from "lucide-react";
import { accentVar, categoryMeta } from "../categories";
import { PREFS_EVENT, isFavorite, toggleFavorite } from "../prefs";
import type { ToolInfo } from "../types";

export default function ToolCard({ tool }: { tool: ToolInfo }) {
  const meta = categoryMeta(tool.category);
  const Icon = meta.icon;
  const accent = accentVar(meta.accent);
  const disabled = !tool.available;
  const [fav, setFav] = useState(() => isFavorite(tool.slug));

  useEffect(() => {
    const sync = () => setFav(isFavorite(tool.slug));
    window.addEventListener(PREFS_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(PREFS_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, [tool.slug]);

  return (
    <div className="relative rounded-xl border border-line bg-surface transition-colors hover:border-primary">
      <Link
        to={`/tool/${tool.slug}`}
        className="flex h-full items-start gap-3 rounded-xl py-4 pr-12 pl-4"
      >
        <span
          className="grid size-9 shrink-0 place-items-center rounded-lg"
          style={{ background: `color-mix(in srgb, ${accent} 11%, var(--color-surface))` }}
        >
          <Icon aria-hidden className="size-4.5 text-fg" />
        </span>
        <span className="min-w-0">
          <span className="block text-sm font-semibold leading-snug text-fg">{tool.name}</span>
          <span className="mt-1 line-clamp-2 text-sm leading-snug text-muted">{tool.description}</span>
          {disabled && <span className="mt-1 block text-xs font-medium text-muted">Needs setup</span>}
        </span>
      </Link>
      <button
        type="button"
        onClick={() => setFav(toggleFavorite(tool.slug))}
        title={fav ? "Remove from saved tools" : "Save tool"}
        aria-label={`Save ${tool.name}`}
        aria-pressed={fav}
        className={`absolute right-1.5 top-1.5 grid size-10 place-items-center rounded-lg hover:bg-surface-2 ${fav ? "text-primary" : "text-muted"}`}
      >
        <Star aria-hidden className="size-4" fill={fav ? "currentColor" : "none"} />
      </button>
    </div>
  );
}
