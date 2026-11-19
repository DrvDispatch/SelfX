import { useState } from "react";
import { Link } from "react-router-dom";
import { Clock3, Eye, FileText, Trash2, XCircle } from "lucide-react";
import type { Job } from "../types";
import { formatDate, formatDuration } from "../format";
import { jobStep, jobTitle } from "../jobProgress";
import FilePreview from "./FilePreview";
import StatusBadge from "./StatusBadge";

interface Props {
  job: Job;
  highlighted: boolean;
  pending?: boolean;
  onCancel: (id: string) => void;
  onDelete: (id: string) => void;
}

export default function JobRow({ job, highlighted, pending, onCancel, onDelete }: Props) {
  const [preview, setPreview] = useState<Job["output_files"][number] | null>(null);
  const active = job.status === "queued" || job.status === "running";
  const workflow = job.tool.startsWith("workflow:");
  const step = active ? jobStep(job) : null;
  const inputs = job.input_files.map((file) => file.orig_name).join(", ");

  return (
    <li className={`rounded-xl border bg-surface p-4 ${highlighted ? "border-primary" : "border-line"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary-soft text-primary">
            <FileText aria-hidden className="size-4" />
          </span>
          <div className="min-w-0">
            {workflow ? (
              <Link className="break-words text-sm font-semibold text-fg underline-offset-2 hover:underline" to={`/runs/${job.id}`}>
                {jobTitle(job)}
              </Link>
            ) : <h3 className="text-sm font-semibold text-fg">{jobTitle(job)}</h3>}
            {inputs && <p title={inputs} className="mt-0.5 truncate text-xs text-muted">{inputs}</p>}
          </div>
        </div>
        <StatusBadge status={job.status} />
      </div>
      {step && (
        <div className="mt-3 space-y-1.5">
          <p className="text-sm text-muted"><span className="mr-2 font-medium text-fg">{step.label}</span>{step.detail}</p>
          {job.status === "running" && <progress className="h-1.5 w-full accent-primary" aria-label={`${jobTitle(job)} progress`}
            max={100} value={step.percent > 0 ? step.percent : undefined} />}
        </div>
      )}
      {job.status === "error" && job.error && <p className="mt-3 break-words text-sm text-danger">{job.error}</p>}
      {job.output_files.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {job.output_files.map((file) => (
            <button key={file.id} type="button" onClick={() => setPreview(file)}
              className="inline-flex min-w-0 items-center gap-1.5 rounded-lg bg-surface-2 px-2.5 py-1.5 text-xs font-medium text-primary hover:bg-primary-soft">
              <Eye aria-hidden className="size-3.5 shrink-0" /><span className="break-all">{file.orig_name}</span>
            </button>
          ))}
        </div>
      )}
      <div className="mt-3 flex min-h-8 flex-wrap items-center justify-between gap-2 text-xs text-muted">
        <span className="inline-flex items-center gap-1.5">
          <Clock3 aria-hidden className="size-3.5" /> {formatDate(job.created_at)}
          {job.finished_at && job.started_at && ` · ${formatDuration(job.started_at, job.finished_at)}`}
        </span>
        {job.status === "queued" && (
          <button type="button" disabled={pending} onClick={() => onCancel(job.id)}
            className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 font-medium hover:bg-surface-2 disabled:opacity-50">
            <XCircle aria-hidden className="size-3.5" /> Cancel
          </button>
        )}
        {!active && (
          <button type="button" disabled={pending} onClick={() => onDelete(job.id)}
            className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-2 font-medium hover:bg-surface-2 hover:text-danger disabled:opacity-50"
            aria-label={`Delete ${jobTitle(job)} job and outputs`}>
            <Trash2 aria-hidden className="size-3.5" /> Delete
          </button>
        )}
      </div>
      {preview && <FilePreview file={preview} onClose={() => setPreview(null)} />}
    </li>
  );
}
