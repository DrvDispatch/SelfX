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

  const onStar = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setFav(toggleFavorite(tool.slug));
  };

  return (
    <Link
      to={`/tool/${tool.slug}`}
      title={disabled ? tool.unavailable_reason ?? "Needs setup" : tool.description}
      className="group relative flex flex-col gap-2.5 rounded-2xl border border-line bg-surface p-4 shadow-[var(--shadow-card)] transition-all duration-150 hover:-translate-y-0.5 hover:shadow-[var(--shadow-pop)]"
      style={{ opacity: disabled ? 0.6 : 1 }}
    >
      <button
        type="button"
        onClick={onStar}
        title={fav ? "Remove from favorites" : "Add to favorites"}
        aria-label={fav ? "Remove from favorites" : "Add to favorites"}
        className={`absolute right-2.5 top-2.5 grid h-7 w-7 place-items-center rounded-full transition-all hover:bg-surface-2 ${
          fav ? "text-primary" : "text-faint opacity-0 group-hover:opacity-100 focus:opacity-100"
        }`}
      >
        <Star className="h-4 w-4" fill={fav ? "currentColor" : "none"} />
      </button>
      <div className="flex items-center gap-3 pr-7">
        <span
          className="grid h-10 w-10 shrink-0 place-items-center rounded-xl"
          style={{ background: `color-mix(in srgb, ${accent} 14%, transparent)` }}
        >
          <Icon className="h-5 w-5" style={{ color: accent }} />
        </span>
        <span className="min-w-0 flex-1 font-semibold leading-tight text-fg">{tool.name}</span>
      </div>
      <p className="line-clamp-2 text-sm leading-snug text-muted">{tool.description}</p>
      {disabled && (
        <span className="mt-auto inline-flex w-fit items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-[11px] font-medium text-faint">
          needs setup
        </span>
      )}
    </Link>
  );
}
