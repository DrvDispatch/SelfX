import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Layers, Play } from "lucide-react";
import { ApiError, createBatchJob, listTools, uploadFileWithProgress } from "../api";
import FileDrop from "../components/FileDrop";
import ParamsForm from "../components/ParamsForm";
import { useToast } from "../components/Toast";
import type { ToolInfo } from "../types";

export default function Batch() {
  const navigate = useNavigate();
  const toast = useToast();
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [slug, setSlug] = useState<string>("");
  const [files, setFiles] = useState<File[]>([]);
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [step, setStep] = useState<string | null>(null);

  // Batch only makes sense for tools that take exactly one file per run.
  const batchable = useMemo(
    () => tools.filter((t) => t.min_files === 1 && !t.multi_file),
    [tools],
  );
  const tool = useMemo(() => batchable.find((t) => t.slug === slug) ?? null, [batchable, slug]);

  useEffect(() => {
    let cancelled = false;
    listTools()
      .then((all) => {
        if (cancelled) return;
        setTools(all);
      })
      .catch((e: unknown) => {
        if (!cancelled) setLoadError(e instanceof ApiError ? e.detail : "Failed to load tools");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Reset files + prefill param defaults when the chosen tool changes.
  useEffect(() => {
    if (!tool) return;
    const init: Record<string, unknown> = {};
    for (const [name, prop] of Object.entries(tool.params_schema.properties ?? {})) {
      if (prop.default !== undefined) init[name] = prop.default;
    }
    setParams(init);
    setFiles([]);
    setSubmitError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  const validationError = useMemo(() => {
    if (!tool) return "Choose a tool to run";
    if (files.length < 1) return "Add at least one file";
    for (const name of tool.params_schema.required ?? []) {
      const v = params[name];
      if (v === undefined || v === null || (typeof v === "string" && v.trim() === "")) {
        const title = tool.params_schema.properties?.[name]?.title ?? name;
        return `"${title}" is required`;
      }
    }
    return null;
  }, [tool, files, params]);

  const onRun = async () => {
    if (!tool || submitting || validationError) return;
    setSubmitError(null);
    setSubmitting(true);
    try {
      const fileIds: string[] = [];
      for (let i = 0; i < files.length; i++) {
        setStep(`Uploading ${i + 1}/${files.length}: ${files[i].name}…`);
        const info = await uploadFileWithProgress(files[i], (frac) =>
          setStep(`Uploading ${i + 1}/${files.length}: ${files[i].name} — ${Math.round(frac * 100)}%`),
        );
        fileIds.push(info.id);
      }
      setStep("Starting batch…");
      const cleaned: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(params)) {
        if (v !== undefined && v !== "") cleaned[k] = v;
      }
      const job = await createBatchJob(tool.slug, fileIds, cleaned);
      toast.success(`Batch of ${files.length} started — tracking it in Jobs`);
      navigate(`/jobs?highlight=${job.id}`);
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : "Failed to start batch";
      setSubmitError(detail);
      toast.error(detail);
      setSubmitting(false);
      setStep(null);
    }
  };

  if (loading) return <div className="p-6 text-sm text-muted">Loading…</div>;

  return (
    <div className="mx-auto max-w-2xl p-6">
      <Link
        to="/"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-fg"
      >
        <ArrowLeft className="h-4 w-4" />
        Dashboard
      </Link>
      <div className="mb-6 flex items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary-soft">
          <Layers className="h-5 w-5 text-primary" />
        </span>
        <div>
          <h1 className="text-xl font-bold text-fg">Batch</h1>
          <p className="mt-1 text-sm text-muted">
            Run one tool across many files at once. Results come back as a single zip,
            one folder per file.
          </p>
        </div>
      </div>

      {loadError && (
        <p className="mb-4 rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-danger">
          {loadError}
        </p>
      )}

      <section className="mb-6">
        <h2 className="mb-2 text-sm font-medium text-fg">Tool</h2>
        <select
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          disabled={submitting}
          className="w-full rounded-xl border border-line bg-surface-2 px-3 py-2.5 text-sm text-fg outline-none focus:border-primary disabled:opacity-60"
        >
          <option value="">Select a tool…</option>
          {batchable.map((t) => (
            <option key={t.slug} value={t.slug} disabled={!t.available}>
              {t.name}
              {!t.available ? " (unavailable)" : ""}
            </option>
          ))}
        </select>
        {tool && <p className="mt-1.5 text-xs text-muted">{tool.description}</p>}
      </section>

      {tool && (
        <>
          <section className="mb-6">
            <h2 className="mb-2 text-sm font-medium text-fg">
              Files <span className="font-normal text-muted">(one job per file)</span>
            </h2>
            <FileDrop
              accepts={tool.accepts}
              multiple
              files={files}
              onChange={setFiles}
              disabled={submitting || !tool.available}
            />
          </section>

          {Object.keys(tool.params_schema.properties ?? {}).length > 0 && (
            <section className="mb-6">
              <h2 className="mb-2 text-sm font-medium text-fg">
                Options <span className="font-normal text-muted">(applied to every file)</span>
              </h2>
              <ParamsForm
                schema={tool.params_schema}
                values={params}
                onChange={(name, value) => setParams((prev) => ({ ...prev, [name]: value }))}
                disabled={submitting || !tool.available}
              />
            </section>
          )}
        </>
      )}

      {submitError && (
        <p className="mb-4 rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-danger">
          {submitError}
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => void onRun()}
          disabled={submitting || validationError !== null}
          title={validationError ?? undefined}
          className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-fg transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Play className="h-4 w-4" />
          {submitting ? "Running…" : `Run on ${files.length || 0} file${files.length === 1 ? "" : "s"}`}
        </button>
        {submitting && step && <span className="text-sm text-muted">{step}</span>}
        {!submitting && validationError && tool && (
          <span className="text-sm text-muted">{validationError}</span>
        )}
      </div>
    </div>
  );
}
