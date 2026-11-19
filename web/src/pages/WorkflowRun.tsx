import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Download, FileText, Loader2, PencilLine, RotateCcw } from "lucide-react";
import { ApiError, cancelJob, downloadFile, getWorkflowRun, retryWorkflowRun, streamJobEvents, type WorkflowPlan } from "../api";
import { useConfirm } from "../components/ConfirmDialog";
import SaveRecipe from "../components/SaveRecipe";
import StatusBadge from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import WorkflowSteps from "../components/WorkflowSteps";
import { formatBytes } from "../format";
import type { FileInfo, Job } from "../types";

function isActive(run: Job) {
  return run.status === "queued" || run.status === "running";
}

const TRANSCRIPT_STEPS: WorkflowPlan = { steps: [
  { id: "transcribe", action: "transcribe", input: "source", params: {} },
  { id: "pdf", action: "export-pdf", input: "transcribe.transcript", params: {} },
  { id: "captions", action: "export-srt", input: "transcribe.transcript", params: {} },
] };

function currentStep(run: Job, plan: WorkflowPlan): number | undefined {
  if (run.status !== "running") return;
  const message = run.message ?? "";
  if (run.tool === "workflow:transcript-pdf") {
    if (/exporting captions|transcript exports ready/i.test(message)) return 3;
    if (/formatting transcript PDF|using saved transcript/i.test(message)) return 2;
    return 1;
  }
  const match = /^Step (\d+)\/(\d+)\s*·/i.exec(message);
  const step = Number(match?.[1]);
  if (match && Number(match[2]) === plan.steps.length && step >= 1 && step <= plan.steps.length) return step;
}

function isTranscript(filename: string): boolean {
  return /(?:^|-)transcript\.json$/i.test(filename);
}

export default function WorkflowRunRoute() {
  const { id } = useParams<{ id: string }>();
  return id ? <WorkflowRun key={id} id={id} /> : null;
}

function WorkflowRun({ id }: { id: string }) {
  const confirm = useConfirm();
  const navigate = useNavigate();
  const toast = useToast();
  const [run, setRun] = useState<Job | null>(null);
  const [readError, setReadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [action, setAction] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let pending = false;
    let replay = false;
    let finished = false;
    let updates = 0;
    let stop = () => {};

    async function refresh() {
      if (controller.signal.aborted || finished) return;
      if (pending) {
        replay = true;
        return;
      }
      pending = true;
      const seen = updates;
      try {
        const snapshot = await getWorkflowRun(id, controller.signal);
        if (controller.signal.aborted) return;
        finished = !isActive(snapshot);
        setRun((previous) => {
          if (previous && !finished && seen !== updates && previous.progress >= snapshot.progress) return previous;
          return snapshot;
        });
        setReadError(null);
        if (finished) stop();
      } catch (error) {
        if (controller.signal.aborted) return;
        setReadError(error instanceof ApiError ? error.detail : "Could not read the workflow status.");
        if (error instanceof ApiError && [403, 404, 410].includes(error.status)) {
          finished = true;
          stop();
        }
      } finally {
        pending = false;
        if (replay) {
          replay = false;
          void refresh();
        }
      }
    }

    stop = streamJobEvents((event) => {
      if (event.id !== id || finished) return;
      const { status, progress, message } = event;
      if (status !== "running" && status !== "queued") {
        void refresh();
        return;
      }
      updates++;
      setRun((previous) => {
        if (!previous || !isActive(previous) || (previous.status === "running" && status === "queued")) return previous;
        return { ...previous, status, progress: Math.max(previous.progress, progress), message };
      });
    });
    void refresh();
    const interval = window.setInterval(() => void refresh(), 5000);

    return () => {
      controller.abort();
      stop();
      window.clearInterval(interval);
    };
  }, [id, revision]);

  async function changeRun(kind: "retry" | "cancel") {
    if (action) return;
    if (kind === "cancel" && !(await confirm({
      title: "Cancel this workflow?",
      message: "You can start another workflow from Create.",
      confirmLabel: "Cancel workflow",
      cancelLabel: "Keep workflow",
    }))) return;
    setAction(kind);
    setActionError(null);
    try {
      const current = await (kind === "retry" ? retryWorkflowRun(id) : cancelJob(id));
      toast.success(kind === "retry" ? "Workflow queued for another attempt." : "Queued workflow canceled.");
      if (current.id !== id) {
        navigate(`/runs/${current.id}`, { replace: true });
      } else {
        setRun(current);
        setRevision((value) => value + 1);
      }
    } catch (error) {
      setActionError(error instanceof ApiError ? error.detail : "Could not update the workflow.");
    } finally {
      setAction(null);
    }
  }

  async function save(file: FileInfo) {
    if (action) return;
    setAction(file.id);
    setActionError(null);
    try {
      await downloadFile(file);
    } catch (error) {
      setActionError(error instanceof ApiError ? error.detail : "Could not download the file.");
    } finally {
      setAction(null);
    }
  }

  const pct = run ? Math.round(Math.max(0, Math.min(1, run.progress)) * 100) : 0;
  const input = run?.input_files[0]?.orig_name;
  const title = typeof run?.params.title === "string" && run.params.title ? run.params.title
    : run?.tool === "workflow:transcript-pdf" ? "Transcript workflow" : "Workflow";
  const plan = run?.tool === "workflow:actions" ? run.params.plan as WorkflowPlan : undefined;
  const timeline = run?.tool === "workflow:transcript-pdf" ? TRANSCRIPT_STEPS : plan;
  const reusable: WorkflowPlan | undefined = run?.tool === "workflow:transcript-pdf"
    ? { steps: [{ id: "recording", action: "transcript-pdf", input: "source", params: {
      language: typeof run.params.language === "string" ? run.params.language : "auto",
    } }] }
    : plan;

  return (
    <div className="mx-auto max-w-3xl">
      <Link to="/jobs" className="mb-4 inline-flex min-h-9 items-center gap-2 text-sm font-medium text-muted hover:text-fg">
        <ArrowLeft aria-hidden="true" className="size-4" /> Activity
      </Link>
      <section className="rounded-2xl border border-line bg-surface p-4 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="break-words text-2xl font-semibold tracking-tight text-fg">{title}</h1>
            {input && <p className="mt-1 break-all text-sm text-muted">{input}</p>}
          </div>
          {run && <StatusBadge status={run.status} />}
        </div>
        {!run && !readError && (
          <p className="mt-4 flex items-center gap-2 text-sm text-muted" role="status">
            <Loader2 aria-hidden="true" className="size-4 motion-safe:animate-spin" /> Loading workflow…
          </p>
        )}
        {run && isActive(run) && (
          <div className="mt-5">
            <p role="status" className="mb-2 text-sm text-muted">{run.message || (run.status === "queued" ? "Waiting for a worker" : "Starting work")}</p>
            {run.status === "running" && (
              <progress className="block h-2 w-full accent-primary" value={pct > 0 ? pct : undefined} max={100} aria-label="Workflow progress" />
            )}
          </div>
        )}
        {run?.status === "error" && <p className="mt-4 break-words text-sm text-danger" role="alert">{run.error || "The workflow failed."}</p>}
        {readError && (
          <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
            <p role="status" className="text-muted">{readError}</p>
            <button type="button" className="font-medium text-primary underline" onClick={() => setRevision((value) => value + 1)}>Refresh status</button>
          </div>
        )}
        {(run?.status === "queued" || run?.status === "error") && (
          <button
            type="button"
            disabled={action !== null}
            className="mt-4 inline-flex min-h-10 items-center gap-2 rounded-lg border border-line px-3 text-sm font-medium text-fg hover:bg-surface-2 disabled:opacity-50"
            onClick={() => void changeRun(run.status === "queued" ? "cancel" : "retry")}
          >
            {run.status === "queued" ? "Cancel queued workflow" : <><RotateCcw aria-hidden="true" className="size-4" /> Retry workflow</>}
          </button>
        )}
        {timeline && run && (
          <section className="mt-4 border-t border-line pt-4" aria-label="Workflow steps">
            <h2 className="text-sm font-semibold text-fg">Workflow steps</h2>
            <WorkflowSteps plan={timeline} activeStep={currentStep(run, timeline)} complete={run.status === "done"} />
          </section>
        )}
        {reusable && (
          <div className="mt-4 flex flex-wrap gap-2">
            <SaveRecipe plan={reusable} suggestedName={run?.tool === "workflow:transcript-pdf" ? "Transcript PDF and captions" : undefined} />
          </div>
        )}
      </section>

      {run && run.output_files.length > 0 && (
        <section className="mt-4 rounded-2xl border border-line bg-surface p-4 sm:p-6" aria-labelledby="run-results">
          <h2 id="run-results" className="text-lg font-semibold text-fg">Results</h2>
          <ul className="mt-2 divide-y divide-line">
            {run.output_files.map((file) => (
              <li key={file.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="flex min-w-0 items-center gap-2">
                  <FileText aria-hidden="true" className="size-5 shrink-0 text-primary" />
                  <div className="min-w-0">
                    <p className="break-all text-sm font-medium text-fg">{file.orig_name}</p>
                    <p className="text-xs text-muted">{formatBytes(file.size)}</p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {isTranscript(file.orig_name) && (
                    <Link
                      to={`/runs/${run.id}/transcript/${file.id}`}
                      className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line px-2.5 text-sm font-medium text-primary hover:bg-surface-2"
                    >
                      <PencilLine aria-hidden="true" className="size-4" /> Edit transcript
                    </Link>
                  )}
                  <Link
                    to="/"
                    state={{ input: file }}
                    className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line px-2.5 text-sm font-medium text-primary hover:bg-surface-2"
                    aria-label={`Use ${file.orig_name} as input`}
                  >
                    <ArrowRight aria-hidden="true" className="size-4" /> <span className="hidden sm:inline">Use as input</span>
                  </Link>
                  <button
                    type="button"
                    disabled={action !== null}
                    className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line px-2.5 text-sm font-medium text-primary hover:bg-surface-2 disabled:opacity-50"
                    onClick={() => void save(file)}
                    aria-label={`Download ${file.orig_name}`}
                  >
                    <Download aria-hidden="true" className="size-4" /> <span className="hidden sm:inline">Download</span>
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
      {run?.status === "done" && run.output_files.length === 0 && <p className="mt-4 text-sm text-muted">These results may have expired.</p>}
      {actionError && <p role="alert" className="mt-4 break-words text-sm text-danger">{actionError}</p>}
    </div>
  );
}
