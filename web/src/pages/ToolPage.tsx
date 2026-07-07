import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Play } from "lucide-react";
import { ApiError, createJob, listTools, uploadFile } from "../api";
import FileDrop from "../components/FileDrop";
import ParamsForm from "../components/ParamsForm";
import type { ToolInfo } from "../types";

export default function ToolPage() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  // Files carried over from the dashboard's "drop a file → suggested tools" flow.
  const presetFiles = (location.state as { presetFiles?: File[] } | null)?.presetFiles;
  const [tool, setTool] = useState<ToolInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [step, setStep] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listTools()
      .then((tools) => {
        if (cancelled) return;
        const found = tools.find((t) => t.slug === slug) ?? null;
        setTool(found);
        if (!found) setLoadError("Tool not found");
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setLoadError(e instanceof ApiError ? e.detail : "Failed to load tool");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  // Pre-fill defaults from the schema whenever the tool changes.
  useEffect(() => {
    if (!tool) return;
    const init: Record<string, unknown> = {};
    for (const [name, prop] of Object.entries(tool.params_schema.properties ?? {})) {
      if (prop.default !== undefined) init[name] = prop.default;
    }
    setParams(init);
    if (presetFiles?.length && tool.min_files > 0) {
      const acc = tool.accepts.map((a) => a.toLowerCase());
      const matched = presetFiles.filter(
        (f) => acc.length === 0 || acc.some((a) => f.name.toLowerCase().endsWith(a)),
      );
      setFiles(tool.multi_file ? matched : matched.slice(0, 1));
    } else {
      setFiles([]);
    }
    setSubmitError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool]);

  const validationError = useMemo(() => {
    if (!tool) return null;
    if (files.length < tool.min_files) {
      return tool.min_files === 1
        ? "Add a file to run this tool"
        : `This tool needs at least ${tool.min_files} files`;
    }
    if (!tool.multi_file && files.length > 1) {
      return "This tool takes a single file";
    }
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
        setStep(`Uploading ${i + 1}/${files.length}: ${files[i].name}`);
        const info = await uploadFile(files[i]);
        fileIds.push(info.id);
      }
      setStep("Creating job…");
      const cleaned: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(params)) {
        if (v !== undefined && v !== "") cleaned[k] = v;
      }
      const job = await createJob(tool.slug, fileIds, cleaned);
      navigate(`/jobs?highlight=${job.id}`);
    } catch (e) {
      setSubmitError(e instanceof ApiError ? e.detail : "Failed to start job");
      setSubmitting(false);
      setStep(null);
    }
  };

  if (loading) {
    return <div className="p-6 text-sm text-muted">Loading…</div>;
  }
  if (loadError || !tool) {
    return (
      <div className="p-6">
        <p className="mb-4 rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-danger">
          {loadError ?? "Tool not found"}
        </p>
        <Link to="/" className="text-sm text-primary hover:underline">
          Back to dashboard
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl p-6">
      <Link
        to="/"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-fg"
      >
        <ArrowLeft className="h-4 w-4" />
        Dashboard
      </Link>
      <div className="mb-6">
        <h1 className="text-xl font-bold text-fg">{tool.name}</h1>
        <p className="mt-1 text-sm text-muted">{tool.description}</p>
      </div>

      {!tool.available && (
        <p className="mb-4 rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-warn">
          Tool unavailable{tool.unavailable_reason ? `: ${tool.unavailable_reason}` : ""}
        </p>
      )}

      {tool.min_files > 0 && (
        <section className="mb-6">
          <h2 className="mb-2 text-sm font-medium text-fg">
            Files
            {tool.multi_file && (
              <span className="ml-2 font-normal text-muted">
                (min {tool.min_files}
                {tool.min_files > 1 ? ", order matters" : ""})
              </span>
            )}
          </h2>
          <FileDrop
            accepts={tool.accepts}
            multiple={tool.multi_file}
            files={files}
            onChange={setFiles}
            disabled={submitting || !tool.available}
          />
        </section>
      )}

      <section className="mb-6">
        <h2 className="mb-2 text-sm font-medium text-fg">Options</h2>
        <ParamsForm
          schema={tool.params_schema}
          values={params}
          onChange={(name, value) =>
            setParams((prev) => ({ ...prev, [name]: value }))
          }
          disabled={submitting || !tool.available}
        />
      </section>

      {submitError && (
        <p className="mb-4 rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-danger">
          {submitError}
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => void onRun()}
          disabled={submitting || !tool.available || validationError !== null}
          title={validationError ?? undefined}
          className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-fg transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Play className="h-4 w-4" />
          {submitting ? "Running…" : "Run"}
        </button>
        {submitting && step && (
          <span className="text-sm text-muted">{step}</span>
        )}
        {!submitting && validationError && (
          <span className="text-sm text-muted">{validationError}</span>
        )}
      </div>
    </div>
  );
}
