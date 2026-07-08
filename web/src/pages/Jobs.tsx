import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ListChecks } from "lucide-react";
import { ApiError, cancelJob, deleteJob, listJobs, streamJobEvents } from "../api";
import JobRow from "../components/JobRow";
import { RowsSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useConfirm } from "../components/ConfirmDialog";
import type { Job } from "../types";

const PAGE_SIZE = 100;

export default function Jobs() {
  const toast = useToast();
  const confirm = useConfirm();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const highlight = searchParams.get("highlight");
  const announced = useRef<Set<string>>(new Set());
  const jobsRef = useRef<Job[]>([]);
  useEffect(() => { jobsRef.current = jobs; }, [jobs]);

  const load = useCallback(async () => {
    try {
      const res = await listJobs(PAGE_SIZE, 0);
      setJobs(res.items);
      setTotal(res.total);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Live updates via SSE: patch rows in place, and on completion toast (once) +
  // reload to pull in the finished job's output files.
  useEffect(() => {
    const stop = streamJobEvents((e) => {
      const known = jobsRef.current.some((j) => j.id === e.id);
      if (known) {
        setJobs((prev) =>
          prev.map((j) => (j.id === e.id ? { ...j, status: e.status as Job["status"], progress: e.progress, message: e.message } : j)),
        );
      }
      if ((e.status === "done" || e.status === "error") && !announced.current.has(e.id)) {
        announced.current.add(e.id);
        if (e.status === "done") toast.success(`“${e.tool}” finished`);
        else toast.error(`“${e.tool}” failed`);
        void load(); // refresh to pull output files
      } else if (!known) {
        void load(); // a job we haven't seen yet (e.g. just created)
      }
    });
    return stop;
  }, [load, toast]);

  // Safety-net reconcile in case the SSE stream drops (proxies, sleep, etc.).
  useEffect(() => {
    const active = jobs.some((j) => j.status === "queued" || j.status === "running");
    if (!active) return;
    const timer = setInterval(() => void load(), 8000);
    return () => clearInterval(timer);
  }, [jobs, load]);

  const onCancel = async (id: string) => {
    if (!(await confirm({ title: "Cancel this job?", message: "It will stop and be marked as canceled.", confirmLabel: "Cancel job", cancelLabel: "Keep running" }))) return;
    try {
      await cancelJob(id);
      toast.info("Job canceled");
      await load();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Cancel failed");
    }
  };

  const onDelete = async (id: string) => {
    if (!(await confirm({ title: "Delete this job?", message: "The job and its output files will be removed.", danger: true, confirmLabel: "Delete" }))) return;
    try {
      await deleteJob(id);
      toast.success("Job deleted");
      await load();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Delete failed");
    }
  };

  const activeCount = jobs.filter((j) => j.status === "queued" || j.status === "running").length;

  return (
    <div className="mx-auto max-w-6xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-fg">Jobs</h1>
          <p className="text-sm text-muted">
            {total} job{total === 1 ? "" : "s"} total
            {activeCount > 0 && <span className="text-primary"> · {activeCount} active</span>}
          </p>
        </div>
      </div>

      {error && (
        <p className="mb-4 rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-danger">{error}</p>
      )}

      {loading ? (
        <RowsSkeleton count={5} />
      ) : jobs.length === 0 ? (
        <div className="rounded-2xl border border-line bg-surface p-10 text-center shadow-[var(--shadow-card)]">
          <span className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-surface-2">
            <ListChecks className="h-6 w-6 text-faint" />
          </span>
          <p className="text-sm text-muted">No jobs yet — your runs will show up here.</p>
          <Link to="/" className="mt-3 inline-block rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-fg transition-opacity hover:opacity-90">
            Pick a tool
          </Link>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-line bg-surface shadow-[var(--shadow-card)]">
          <table className="w-full min-w-[720px] text-left">
            <thead>
              <tr className="border-b border-line bg-surface-2 text-xs uppercase tracking-wide text-faint">
                <th className="px-3 py-2 font-medium">Tool</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Progress</th>
                <th className="px-3 py-2 font-medium">Created</th>
                <th className="px-3 py-2 font-medium">Duration</th>
                <th className="px-3 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <JobRow
                  key={job.id}
                  job={job}
                  highlighted={job.id === highlight}
                  onCancel={(id) => void onCancel(id)}
                  onDelete={(id) => void onDelete(id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
