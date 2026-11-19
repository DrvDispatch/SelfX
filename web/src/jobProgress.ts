import type { Job } from "./types";

export function jobTitle(job: Job): string {
  if (job.tool.startsWith("workflow:") && typeof job.params.title === "string" && job.params.title.trim()) {
    return job.params.title;
  }
  if (job.tool === "workflow:transcript-pdf") return "Transcript workflow";
  if (job.tool === "workflow:actions") return "File workflow";
  if (job.tool.startsWith("pipeline:")) return "Tool pipeline";
  return job.tool.replace(/^batch:/, "Batch ").replace(/-/g, " ").replace(/^\w/, (character) => character.toUpperCase());
}

export function jobStep(job: Job): { label: string; detail: string; percent: number } {
  const percent = Math.round(Math.min(1, Math.max(0, job.progress)) * 100);
  if (job.status === "queued") return { label: "Queued", detail: "Waiting for a worker", percent };
  const named = /^step\s+(\d+)\/(\d+)\s*[·:]?\s*(.*)$/i.exec(job.message ?? "");
  if (named) return { label: `Step ${named[1]} of ${named[2]}`, detail: named[3], percent };
  if (job.tool === "workflow:transcript-pdf") {
    const message = job.message ?? "";
    if (/captions|exports ready/i.test(message)) return { label: "Step 3 of 3", detail: "Export captions", percent };
    if (/formatting|saved transcript/i.test(message)) return { label: "Step 2 of 3", detail: "Format the transcript PDF", percent };
    return { label: "Step 1 of 3", detail: message || "Transcribe the recording", percent };
  }
  return { label: "In progress", detail: job.message || "Preparing the next operation", percent };
}
