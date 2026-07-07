import { Link } from "react-router-dom";
import { accentVar, categoryMeta } from "../categories";
import type { ToolInfo } from "../types";

export default function ToolCard({ tool }: { tool: ToolInfo }) {
  const meta = categoryMeta(tool.category);
  const Icon = meta.icon;
  const accent = accentVar(meta.accent);
  const disabled = !tool.available;

  return (
    <Link
      to={`/tool/${tool.slug}`}
      title={disabled ? tool.unavailable_reason ?? "Needs setup" : tool.description}
      className="group relative flex flex-col gap-2.5 rounded-2xl border border-line bg-surface p-4 shadow-[var(--shadow-card)] transition-all duration-150 hover:-translate-y-0.5 hover:shadow-[var(--shadow-pop)]"
      style={{ opacity: disabled ? 0.6 : 1 }}
    >
      <div className="flex items-center gap-3">
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
