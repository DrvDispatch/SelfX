import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Activity, ArrowRight, ChevronLeft, ChevronRight, Library, RefreshCw } from "lucide-react";
import { ApiError, cancelJob, deleteJob, listJobs, streamJobEvents, type JobEvent } from "../api";
import JobRow from "../components/JobRow";
import { RowsSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useConfirm } from "../components/ConfirmDialog";
import type { Job } from "../types";

const PAGE_SIZE = 20;
const FILTERS = { all: "All", active: "Active", done: "Completed", error: "Needs attention" } as const;
type Filter = keyof typeof FILTERS;
const live = (job: Job) => job.status === "queued" || job.status === "running";
const tabClass = "min-h-10 rounded-lg px-3 text-sm font-medium";

function applyEvent(items: Job[], event: JobEvent): Job[] {
  return items.map((job) => {
    if (job.id !== event.id || (event.status === "queued" && job.status === "running")) return job;
    return { ...job, status: event.status as Job["status"], progress: event.progress, message: event.message };
  });
}

export default function Jobs() {
  const toast = useToast();
  const confirm = useConfirm();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [active, setActive] = useState<Job[]>([]);
  const [activeTotal, setActiveTotal] = useState(0);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const highlight = searchParams.get("highlight");
  const request = useRef<AbortController | null>(null);
  const knownIds = useRef(new Set<string>());
  const announced = useRef(new Set<string>());

  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setRefreshing(true);
    try {
      const [history, current] = await Promise.all([
        listJobs(PAGE_SIZE, page * PAGE_SIZE, filter, controller.signal),
        listJobs(4, 0, "active", controller.signal),
      ]);
      if (controller.signal.aborted) return;
      const last = Math.max(0, Math.ceil(history.total / PAGE_SIZE) - 1);
      if (page > last) { setPage(last); return; }
      knownIds.current = new Set([...history.items, ...current.items].map((job) => job.id));
      setJobs(history.items);
      setActive(current.items);
      setTotal(history.total);
      setActiveTotal(current.total);
      setError("");
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof ApiError ? failure.detail : "Could not load activity.");
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [filter, page]);

  useEffect(() => {
    void load();
    return () => request.current?.abort();
  }, [load]);

  useEffect(() => {
    let refreshTimer: number | undefined;
    const stop = streamJobEvents((event) => {
      if (!["queued", "running", "done", "error", "canceled"].includes(event.status)) return;
      setJobs((items) => applyEvent(items, event));
      setActive((items) => applyEvent(items, event).filter(live));
      const terminal = ["done", "error", "canceled"].includes(event.status);
      if (event.status === "queued") announced.current.delete(event.id);
      if (terminal && knownIds.current.has(event.id) && !announced.current.has(event.id)) {
        announced.current.add(event.id);
        if (event.status === "done") toast.success("Your results are ready");
        if (event.status === "error") toast.error("A job needs attention");
      }
      if ((terminal || !knownIds.current.has(event.id)) && refreshTimer === undefined) {
        refreshTimer = window.setTimeout(() => { refreshTimer = undefined; void load(); }, 400);
      }
    });
    // Poll as a fallback for sleeping tabs and connections where events were missed.
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 8000);
    return () => { stop(); window.clearTimeout(refreshTimer); window.clearInterval(timer); };
  }, [load, toast]);

  async function changeJob(id: string, action: "cancel" | "delete") {
    if (pending) return;
    const accepted = await confirm(action === "cancel"
      ? { title: "Cancel queued job?", confirmLabel: "Cancel job", cancelLabel: "Keep job" }
      : { title: "Delete this job?", message: "Its output files will be removed.", danger: true, confirmLabel: "Delete job" });
    if (!accepted) return;
    setPending(id);
    try {
      if (action === "cancel") {
        await cancelJob(id);
        toast.info("Job canceled");
      } else {
        await deleteJob(id);
        toast.success("Job deleted");
      }
      void load();
    } catch (failure) {
      toast.error(failure instanceof ApiError ? failure.detail : "Could not update the job.");
    } finally {
      setPending(null);
    }
  }

  function chooseFilter(next: Filter) {
    setFilter(next);
    setPage(0);
  }

  function row(job: Job) {
    return <JobRow key={job.id} job={job} highlighted={job.id === highlight} pending={job.id === pending}
      onCancel={(id) => void changeJob(id, "cancel")} onDelete={(id) => void changeJob(id, "delete")} />;
  }

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-fg">Activity</h1>
          <p className="mt-1 text-sm text-muted">See live progress and pick up previous work.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/recipes" className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line bg-surface px-3 text-sm font-medium text-fg hover:bg-surface-2">
            <Library aria-hidden className="size-4" /> Recipes
          </Link>
          <button type="button" onClick={() => void load()} disabled={refreshing}
            className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line bg-surface px-3 text-sm font-medium text-fg hover:bg-surface-2 disabled:opacity-50">
            <RefreshCw aria-hidden className="size-4" /> Refresh
          </button>
        </div>
      </header>

      {error && <p className="rounded-xl border border-line bg-surface px-4 py-3 text-sm text-danger" role="alert">{error}</p>}
      {!loading && active.length > 0 && filter !== "active" && (
        <section aria-labelledby="active-jobs">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="active-jobs" className="inline-flex items-center gap-2 text-lg font-semibold text-fg">
              <Activity aria-hidden className="size-4 text-primary" /> In progress <span className="text-sm font-medium text-muted">{activeTotal}</span>
            </h2>
            {activeTotal > active.length && <button type="button" onClick={() => chooseFilter("active")}
              className="text-sm font-medium text-primary hover:underline">Show all active</button>}
          </div>
          <ul className="grid gap-3 lg:grid-cols-2">{active.map(row)}</ul>
        </section>
      )}

      <section aria-labelledby="job-history" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="job-history" className="text-lg font-semibold text-fg">{filter === "active" ? "Active jobs" : "Run history"}</h2>
          <div className="flex flex-wrap gap-1 rounded-lg bg-surface-2 p-1" role="group" aria-label="Filter jobs">
            {(Object.keys(FILTERS) as Filter[]).map((key) => (
              <button key={key} type="button" aria-pressed={filter === key} onClick={() => chooseFilter(key)}
                className={`${tabClass} ${filter === key ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg"}`}>
                {FILTERS[key]}
              </button>
            ))}
          </div>
        </div>
        {loading ? <RowsSkeleton count={4} /> : !jobs.length ? (
          <div className="rounded-xl border border-line bg-surface p-8 text-center">
            <p className="text-sm text-muted">{filter === "all" ? "Your jobs and results will appear here." : "There are no jobs in this view."}</p>
            {filter === "all" && <Link to="/" className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-primary hover:underline">
              Start a workflow <ArrowRight aria-hidden className="size-4" />
            </Link>}
          </div>
        ) : <ul className="grid gap-3 lg:grid-cols-2">{jobs.map(row)}</ul>}
        {pages > 1 && (
          <div className="flex items-center justify-between gap-3">
            <button type="button" aria-label="Previous page" disabled={page === 0} onClick={() => setPage((value) => value - 1)}
              className="grid size-10 place-items-center rounded-lg border border-line bg-surface disabled:opacity-45">
              <ChevronLeft aria-hidden className="size-4" />
            </button>
            <span className="text-sm text-muted">Page {page + 1} of {pages}</span>
            <button type="button" aria-label="Next page" disabled={page + 1 >= pages} onClick={() => setPage((value) => value + 1)}
              className="grid size-10 place-items-center rounded-lg border border-line bg-surface disabled:opacity-45">
              <ChevronRight aria-hidden className="size-4" />
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
