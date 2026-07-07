import type { CSSProperties } from "react";
import type { JobStatus } from "../types";

type BadgeStyle = { text: string; tint?: string };

const STYLES: Record<JobStatus, BadgeStyle> = {
  queued: { text: "text-muted" },
  running: { text: "text-primary", tint: "var(--color-primary)" },
  done: { text: "text-ok", tint: "var(--color-ok)" },
  error: { text: "text-danger", tint: "var(--color-danger)" },
  canceled: { text: "text-faint" },
};

export default function StatusBadge({ status }: { status: JobStatus }) {
  const style = STYLES[status] ?? STYLES.canceled;
  const pill: CSSProperties = style.tint
    ? { background: `color-mix(in srgb, ${style.tint} 12%, transparent)` }
    : {};
  return (
    <span
      style={pill}
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${style.text} ${style.tint ? "" : "bg-surface-2"}`}
    >
      {status === "running" && (
        <span className="mr-1.5 h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
      )}
      {status}
    </span>
  );
}
