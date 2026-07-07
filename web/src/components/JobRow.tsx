import { useState } from "react";
import { Download, Trash2, XCircle } from "lucide-react";
import { downloadFile, ApiError } from "../api";
import { formatDate, formatDuration } from "../format";
import type { Job } from "../types";
import StatusBadge from "./StatusBadge";

interface Props {
  job: Job;
  highlighted: boolean;
  onCancel: (id: string) => void;
  onDelete: (id: string) => void;
}

export default function JobRow({ job, highlighted, onCancel, onDelete }: Props) {
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const active = job.status === "queued" || job.status === "running";
  const pct = Math.round(Math.min(1, Math.max(0, job.progress)) * 100);

  const handleDownload = async (file: Job["output_files"][number]) => {
    setDownloadError(null);
    try {
      await downloadFile(file);
    } catch (e) {
      setDownloadError(e instanceof ApiError ? e.detail : "Download failed");
    }
  };

  return (
    <tr
      className={[
        "border-b border-line text-sm transition-colors",
        highlighted ? "bg-primary-soft" : "hover:bg-surface-2",
      ].join(" ")}
    >
      <td className="px-3 py-2.5 align-top">
        <div className="font-medium text-fg">{job.tool}</div>
        <div className="mt-0.5 truncate text-xs text-muted" title={job.input_files.map((f) => f.orig_name).join(", ")}>
          {job.input_files.length > 0
            ? job.input_files.map((f) => f.orig_name).join(", ")
            : "no input files"}
        </div>
      </td>
      <td className="px-3 py-2.5 align-top">
        <StatusBadge status={job.status} />
        {job.status === "error" && job.error && (
          <div className="mt-1 max-w-56 text-xs text-danger" title={job.error}>
            {job.error}
          </div>
        )}
        {active && job.message && (
          <div className="mt-1 max-w-56 truncate text-xs text-muted" title={job.message}>
            {job.message}
          </div>
        )}
      </td>
      <td className="w-40 px-3 py-2.5 align-top">
        {active ? (
          <div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
              <div
                className="h-full rounded-full bg-primary transition-all duration-500"
                style={{ width: `${job.status === "queued" ? 0 : pct}%` }}
              />
            </div>
            <div className="mt-1 text-xs text-muted">
              {job.status === "queued" ? "waiting…" : `${pct}%`}
            </div>
          </div>
        ) : (
          <span className="text-xs text-faint">
            {job.status === "done" ? "100%" : "—"}
          </span>
        )}
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 align-top text-xs text-muted">
        {formatDate(job.created_at)}
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 align-top text-xs text-muted">
        {formatDuration(job.started_at, job.finished_at)}
      </td>
      <td className="px-3 py-2.5 align-top">
        <div className="flex flex-wrap items-center gap-1.5">
          {job.output_files.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => void handleDownload(f)}
              title={`Download ${f.orig_name}`}
              className="flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:bg-line"
            >
              <Download className="h-3.5 w-3.5" />
              <span className="max-w-36 truncate">{f.orig_name}</span>
            </button>
          ))}
          {active && (
            <button
              type="button"
              onClick={() => onCancel(job.id)}
              title="Cancel job"
              className="flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-1 text-xs font-medium text-warn transition-colors hover:bg-line"
            >
              <XCircle className="h-3.5 w-3.5" />
              Cancel
            </button>
          )}
          <button
            type="button"
            onClick={() => onDelete(job.id)}
            title="Delete job and outputs"
            className="grid h-7 w-7 place-items-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-danger"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
        {downloadError && (
          <p className="mt-1 text-xs text-danger">{downloadError}</p>
        )}
      </td>
    </tr>
  );
}
