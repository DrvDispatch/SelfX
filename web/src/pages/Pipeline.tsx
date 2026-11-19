import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowDown, ArrowLeft, ArrowUp, ChevronRight, Play, Plus, Trash2, Workflow } from "lucide-react";
import { ApiError, createPipelineJob, listTools, uploadFileWithProgress } from "../api";
import FileDrop from "../components/FileDrop";
import ParamsForm from "../components/ParamsForm";
import { useToast } from "../components/Toast";
import type { ToolInfo } from "../types";

interface Step {
  slug: string;
  params: Record<string, unknown>;
}

function defaultsFor(tool: ToolInfo): Record<string, unknown> {
  const init: Record<string, unknown> = {};
  for (const [name, prop] of Object.entries(tool.params_schema.properties ?? {})) {
    if (prop.default !== undefined) init[name] = prop.default;
  }
  return init;
}

export default function Pipeline() {
  const navigate = useNavigate();
  const toast = useToast();
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const chainable = useMemo(
    () => tools.filter((t) => t.min_files === 1 && !t.multi_file),
    [tools],
  );
  const byslug = useMemo(() => new Map(tools.map((t) => [t.slug, t])), [tools]);

  useEffect(() => {
    let cancelled = false;
    listTools()
      .then((all) => !cancelled && setTools(all))
      .catch((e: unknown) => !cancelled && setLoadError(e instanceof ApiError ? e.detail : "Failed to load tools"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const addStep = () => setSteps((s) => [...s, { slug: "", params: {} }]);
  const removeStep = (i: number) => setSteps((s) => s.filter((_, j) => j !== i));
  const move = (i: number, d: -1 | 1) =>
    setSteps((s) => {
      const j = i + d;
      if (j < 0 || j >= s.length) return s;
      const copy = [...s];
      [copy[i], copy[j]] = [copy[j], copy[i]];
      return copy;
    });
  const pickTool = (i: number, slug: string) =>
    setSteps((s) =>
      s.map((step, j) => {
        if (j !== i) return step;
        const t = byslug.get(slug);
        return { slug, params: t ? defaultsFor(t) : {} };
      }),
    );
  const setParam = (i: number, name: string, value: unknown) =>
    setSteps((s) => s.map((step, j) => (j === i ? { ...step, params: { ...step.params, [name]: value } } : step)));

  const validationError = useMemo(() => {
    if (!file) return "Add an input file";
    if (steps.length === 0) return "Add at least one step";
    for (let i = 0; i < steps.length; i++) {
      const t = byslug.get(steps[i].slug);
      if (!t) return `Choose a tool for step ${i + 1}`;
      for (const name of t.params_schema.required ?? []) {
        const v = steps[i].params[name];
        if (v === undefined || v === null || (typeof v === "string" && v.trim() === "")) {
          const title = t.params_schema.properties?.[name]?.title ?? name;
          return `Step ${i + 1}: "${title}" is required`;
        }
      }
    }
    return null;
  }, [file, steps, byslug]);

  const onRun = async () => {
    if (submitting || validationError || !file) return;
    setSubmitError(null);
    setSubmitting(true);
    try {
      setStatus(`Uploading ${file.name}…`);
      const info = await uploadFileWithProgress(file, (frac) =>
        setStatus(`Uploading ${file.name} — ${Math.round(frac * 100)}%`),
      );
      setStatus("Starting pipeline…");
      const payload = steps.map((s) => {
        const cleaned: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(s.params)) {
          if (v !== undefined && v !== "") cleaned[k] = v;
        }
        return { tool: s.slug, params: cleaned };
      });
      const job = await createPipelineJob(payload, [info.id]);
      toast.success(`Pipeline of ${steps.length} step${steps.length === 1 ? "" : "s"} started`);
      navigate(`/jobs?highlight=${job.id}`);
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : "Failed to start pipeline";
      setSubmitError(detail);
      toast.error(detail);
      setSubmitting(false);
      setStatus(null);
    }
  };

  if (loading) return <div className="p-6 text-sm text-muted">Loading…</div>;

  return (
    <div className="mx-auto max-w-2xl p-6">
      <Link to="/tools" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-fg">
        <ArrowLeft className="h-4 w-4" />
        Dashboard
      </Link>
      <div className="mb-6 flex items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary-soft">
          <Workflow className="h-5 w-5 text-primary" />
        </span>
        <div>
          <h1 className="text-xl font-bold text-fg">Pipeline</h1>
          <p className="mt-1 text-sm text-muted">
            Chain tools together — each step runs on the previous step&apos;s output.
            e.g. convert to audio → transcribe → summarize.
          </p>
        </div>
      </div>

      {loadError && (
        <p className="mb-4 rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-danger">{loadError}</p>
      )}

      <section className="mb-6">
        <h2 className="mb-2 text-sm font-medium text-fg">Input file</h2>
        <FileDrop
          accepts={[]}
          multiple={false}
          files={file ? [file] : []}
          onChange={(fs) => setFile(fs[0] ?? null)}
          disabled={submitting}
        />
      </section>

      <section className="mb-6">
        <h2 className="mb-2 text-sm font-medium text-fg">Steps</h2>
        <div className="space-y-3">
          {steps.map((step, i) => {
            const t = byslug.get(step.slug);
            const hasOpts = t && Object.keys(t.params_schema.properties ?? {}).length > 0;
            return (
              <div key={i} className="rounded-2xl border border-line bg-surface-2 p-3">
                <div className="flex items-center gap-2">
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary text-xs font-bold text-primary-fg">
                    {i + 1}
                  </span>
                  <select
                    value={step.slug}
                    onChange={(e) => pickTool(i, e.target.value)}
                    disabled={submitting}
                    className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2.5 py-2 text-sm text-fg outline-none focus:border-primary disabled:opacity-60"
                  >
                    <option value="">Choose a tool…</option>
                    {chainable.map((tool) => (
                      <option key={tool.slug} value={tool.slug} disabled={!tool.available}>
                        {tool.name}
                        {!tool.available ? " (unavailable)" : ""}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => move(i, -1)}
                    disabled={submitting || i === 0}
                    className="grid h-8 w-8 place-items-center rounded-lg text-muted hover:bg-line hover:text-fg disabled:opacity-30"
                    title="Move up"
                  >
                    <ArrowUp className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => move(i, 1)}
                    disabled={submitting || i === steps.length - 1}
                    className="grid h-8 w-8 place-items-center rounded-lg text-muted hover:bg-line hover:text-fg disabled:opacity-30"
                    title="Move down"
                  >
                    <ArrowDown className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => removeStep(i)}
                    disabled={submitting}
                    className="grid h-8 w-8 place-items-center rounded-lg text-muted hover:bg-line hover:text-danger disabled:opacity-30"
                    title="Remove step"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
                {t && <p className="mt-1.5 pl-8 text-xs text-muted">{t.description}</p>}
                {hasOpts && (
                  <div className="mt-3 pl-8">
                    <ParamsForm
                      schema={t!.params_schema}
                      values={step.params}
                      onChange={(name, value) => setParam(i, name, value)}
                      disabled={submitting}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <button
          type="button"
          onClick={addStep}
          disabled={submitting}
          className="mt-3 inline-flex items-center gap-1.5 rounded-xl border border-dashed border-line px-3 py-2 text-sm text-muted transition-colors hover:border-primary hover:text-primary disabled:opacity-50"
        >
          <Plus className="h-4 w-4" /> Add step
        </button>
      </section>

      {steps.some((s) => s.slug) && (
        <div className="mb-6 flex flex-wrap items-center gap-1.5 text-xs text-muted">
          <span className="rounded-full bg-surface-2 px-2 py-1 text-fg">file</span>
          {steps.filter((s) => s.slug).map((s, i) => (
            <span key={i} className="flex items-center gap-1.5">
              <ChevronRight className="h-3.5 w-3.5" />
              <span className="rounded-full bg-primary-soft px-2 py-1 text-primary">
                {byslug.get(s.slug)?.name ?? s.slug}
              </span>
            </span>
          ))}
        </div>
      )}

      {submitError && (
        <p className="mb-4 rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-danger">{submitError}</p>
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
          {submitting ? "Running…" : "Run pipeline"}
        </button>
        {submitting && status && <span className="text-sm text-muted">{status}</span>}
        {!submitting && validationError && <span className="text-sm text-muted">{validationError}</span>}
      </div>
    </div>
  );
}
