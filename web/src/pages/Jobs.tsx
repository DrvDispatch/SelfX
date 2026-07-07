import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, cancelJob, deleteJob, listJobs } from "../api";
import JobRow from "../components/JobRow";
import type { Job } from "../types";

const PAGE_SIZE = 100;

export default function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const highlight = searchParams.get("highlight");

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

  // Poll every 2s only while something is queued or running.
  useEffect(() => {
    const active = jobs.some(
      (j) => j.status === "queued" || j.status === "running",
    );
    if (!active) return;
    const timer = setTimeout(() => {
      void load();
    }, 2000);
    return () => clearTimeout(timer);
  }, [jobs, load]);

  const onCancel = async (id: string) => {
    setActionError(null);
    try {
      await cancelJob(id);
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.detail : "Cancel failed");
    }
  };

  const onDelete = async (id: string) => {
    if (!window.confirm("Delete this job and its output files?")) return;
    setActionError(null);
    try {
      await deleteJob(id);
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.detail : "Delete failed");
    }
  };

  return (
    <div className="mx-auto max-w-6xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-fg">Jobs</h1>
          <p className="text-sm text-muted">
            {total} job{total === 1 ? "" : "s"} total
          </p>
        </div>
      </div>

      {error && (
        <p className="mb-4 rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
      {actionError && (
        <p className="mb-4 rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-danger">
          {actionError}
        </p>
      )}

      {loading ? (
        <p className="text-sm text-muted">Loading jobs…</p>
      ) : jobs.length === 0 ? (
        <div className="rounded-2xl border border-line bg-surface p-8 text-center shadow-[var(--shadow-card)]">
          <p className="text-sm text-muted">No jobs yet.</p>
          <Link
            to="/"
            className="mt-2 inline-block text-sm font-medium text-primary hover:underline"
          >
            Pick a tool on the dashboard
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
