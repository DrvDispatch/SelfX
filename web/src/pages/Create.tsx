import { lazy, Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ArrowDown, ArrowRight, BookOpen, Captions, FileText, Image, LayoutGrid, Mic, Play, ScanText, Server, Sparkles, Workflow, X } from "lucide-react";
import {
  ApiError, createWorkflowRun, draftWorkflowPlan, executeWorkflowPlan, getWorkflowPlanner,
  uploadFileWithProgress, type WorkflowPlan, type WorkflowPlannerStatus,
} from "../api";
import FileDrop from "../components/FileDrop";
import { useToast } from "../components/Toast";
import WorkflowSteps from "../components/WorkflowSteps";
import { acceptsFilename } from "../toolDiscovery";
import type { FileInfo } from "../types";

const SaveRecipe = lazy(() => import("../components/SaveRecipe"));

const INPUT_TYPES = [
  ".mp3", ".wav", ".flac", ".aac", ".ogg", ".opus", ".m4a", ".wma",
  ".aiff", ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v",
];
const RECORDING_PROMPT = "Transcribe this recording into a PDF and create SRT captions.";
const LANGUAGES = {
  auto: "Detect automatically",
  en: "English",
  nl: "Dutch",
  fr: "French",
  de: "German",
  es: "Spanish",
  other: "Other language",
};

const RECORDING_STEPS = [
  { icon: Mic, title: "Transcribe on this server", description: "Whisper converts speech to text." },
  { icon: FileText, title: "Export a PDF", description: "A readable transcript with timestamps." },
  { icon: Captions, title: "Export SRT captions", description: "Subtitle times use the same transcript." },
];

const RECIPES = [
  { id: "creator-captions", title: "Recording to captions", description: "Create a transcript and subtitle files.", icon: Captions },
  { id: "searchable-scan", title: "Make a scan searchable", description: "Turn scanned pages into a searchable PDF.", icon: ScanText },
  { id: "web-image", title: "Prepare a web image", description: "Convert and optimize an image for sharing.", icon: Image },
];

type Mode = "prompt" | "recording";
type Phase = "uploading" | "drafting" | "submitting";
const fieldClass = "w-full rounded-lg border border-line bg-surface px-3 py-2.5 text-sm text-fg placeholder:text-muted";

function idempotencyKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  // randomUUID is unavailable on plain HTTP LAN hosts.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-");
}

export default function Create() {
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const submission = useRef<string | null>(null);
  const inFlight = useRef(false);
  const [choice, setChoice] = useState<Mode | null>(null);
  const [planner, setPlanner] = useState<WorkflowPlannerStatus | null>(null);
  const [plan, setPlan] = useState<WorkflowPlan | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [uploaded, setUploaded] = useState<FileInfo | null>(() => (location.state as { input?: FileInfo } | null)?.input ?? null);
  const [prompt, setPrompt] = useState("");
  const [language, setLanguage] = useState<keyof typeof LANGUAGES>("auto");
  const [customLanguage, setCustomLanguage] = useState("");
  const [title, setTitle] = useState("");
  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState<Phase | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mode = choice ?? (planner?.available ? "prompt" : "recording");
  const recording = mode === "recording";
  const file = files[0];
  const filename = file?.name ?? uploaded?.orig_name;
  const compatible = !filename || !recording || acceptsFilename(filename, INPUT_TYPES);
  const ready = !!filename && compatible && (recording || !!prompt.trim());

  useEffect(() => {
    const controller = new AbortController();
    getWorkflowPlanner(controller.signal)
      .then((status) => { if (!controller.signal.aborted) setPlanner(status); })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  function updateDraft() {
    submission.current = null;
    setPlan(null);
    setError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if ((!file && !uploaded) || !ready || inFlight.current) return;

    inFlight.current = true;
    setError(null);
    try {
      let input = uploaded;
      if (file && !input) {
        setProgress(0);
        setPhase("uploading");
        input = await uploadFileWithProgress(file, setProgress);
        setUploaded(input);
      }
      if (!input) return;
      if (!recording && !plan) {
        setPhase("drafting");
        setPlan(await draftWorkflowPlan(prompt.trim(), input.id));
        return;
      }
      setPhase("submitting");
      const key = submission.current ?? (submission.current = idempotencyKey());
      const run = plan && !recording
        ? await executeWorkflowPlan(input.id, plan, key)
        : await createWorkflowRun({
          file_id: input.id,
          language: language === "other" ? customLanguage.trim().toLowerCase() : language,
          title: title.trim() || undefined,
          prompt: RECORDING_PROMPT,
        }, key);
      toast.success("Workflow queued.");
      navigate(`/runs/${run.id}`);
    } catch (failure) {
      if (failure instanceof ApiError && [404, 410].includes(failure.status)) {
        updateDraft();
        setUploaded(null);
      }
      setError(failure instanceof ApiError ? failure.detail : "Could not continue. Try again.");
    } finally {
      inFlight.current = false;
      setPhase(null);
    }
  }

  const action = phase === "uploading" ? `Uploading ${Math.round(progress * 100)}%`
    : phase === "drafting" ? "Drafting plan…"
    : phase === "submitting" ? "Starting workflow…"
    : recording || plan ? "Start workflow" : "Review a plan";

  return (
    <div className="mx-auto max-w-[74rem]">
      <header className="mb-7 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="max-w-2xl text-[clamp(1.85rem,3.3vw,3.15rem)] leading-[1.06] font-bold tracking-[-0.055em] text-fg">What would you like to make?</h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted sm:text-base">
            {planner?.available ? "Add a file and describe the result you want. Review the steps before you run them." : "Turn a recording into a readable transcript and captions, or start with a recipe."}
          </p>
        </div>
        <Link to="/tools" className="hidden min-h-10 shrink-0 items-center gap-2 rounded-lg border border-line bg-surface px-3 text-sm font-semibold text-fg transition-colors hover:bg-surface-2 sm:inline-flex">
          <LayoutGrid aria-hidden="true" className="size-4" /> Browse tools
        </Link>
      </header>

      <form onSubmit={(event) => void submit(event)} className="grid gap-4 md:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <fieldset disabled={phase !== null} className="min-w-0 rounded-2xl border border-line bg-surface p-4 shadow-[var(--shadow-card)] sm:p-6">
          <legend className="sr-only">File and workflow settings</legend>
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
            {planner?.available ? (
              <div aria-label="Creation mode" role="group" className="grid w-full grid-cols-[0.88fr_1.12fr] gap-1 rounded-xl bg-surface-2 p-1 sm:w-auto">
                <button type="button" aria-pressed={!recording} onClick={() => { setChoice("prompt"); updateDraft(); }}
                  className={`inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg px-1.5 text-xs font-semibold transition-colors sm:px-2.5 sm:text-sm ${recording ? "text-muted hover:text-fg" : "bg-surface text-primary shadow-[var(--shadow-card)]"}`}>
                  <Sparkles aria-hidden="true" className="size-4 shrink-0" /> Describe a task
                </button>
                <button type="button" aria-pressed={recording} onClick={() => { setChoice("recording"); updateDraft(); }}
                  className={`inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg px-1.5 text-xs font-semibold transition-colors sm:px-2.5 sm:text-sm ${recording ? "bg-surface text-primary shadow-[var(--shadow-card)]" : "text-muted hover:text-fg"}`}>
                  <Mic aria-hidden="true" className="size-4 shrink-0" /> Transcribe a recording
                </button>
              </div>
            ) : (
              <h2 className="flex items-center gap-2.5 text-base font-semibold text-fg">
                <span className="grid size-8 place-items-center rounded-lg bg-primary-soft text-primary"><Mic aria-hidden="true" className="size-4.5" /></span>
                Transcribe a recording
              </h2>
            )}
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted"><Server aria-hidden="true" className="size-3.5" /> Runs on this server</span>
          </div>
          <div className="create-picker">
            <h2 className="mb-2 text-sm font-semibold text-fg">{recording ? "Add a recording" : "Add an input file"}</h2>
            <FileDrop
              accepts={recording ? INPUT_TYPES : []}
              formatHint={recording ? "MP4, MOV, MP3, WAV and other audio or video formats" : "Choose one file to get started"}
              multiple={false}
              files={files}
              disabled={phase !== null}
              onChange={(next) => {
                setChoice(mode);
                setFiles(next);
                setUploaded(null);
                updateDraft();
              }}
            />
            {uploaded && !file && (
              <div className="mt-3 flex items-center gap-2 rounded-xl border border-line bg-surface-2 px-3 py-2">
                <FileText aria-hidden="true" className="size-4 shrink-0 text-primary" />
                <p className="min-w-0 flex-1 break-all text-sm font-medium text-fg">{uploaded.orig_name}</p>
                <button type="button" aria-label="Remove attached result" className="rounded-lg p-1.5 text-muted hover:bg-line" onClick={() => {
                  setUploaded(null);
                  updateDraft();
                }}>
                  <X aria-hidden="true" className="size-4" />
                </button>
              </div>
            )}
            {!compatible && <p role="alert" className="mt-2 text-sm text-danger">Choose an audio or video file for the recording workflow. Other files can use manual tools or a configured local planner.</p>}
            {uploaded && file && <p className="mt-2 text-sm text-muted">Uploaded to this server.</p>}
          </div>

          {recording ? (
            <div className="mt-5 space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block space-y-2 text-sm font-semibold text-fg">
                  <span>Spoken language</span>
                  <select className={`${fieldClass} font-normal`} value={language} onChange={(event) => {
                    setLanguage(event.target.value as keyof typeof LANGUAGES);
                    updateDraft();
                  }}>
                    {Object.entries(LANGUAGES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                  </select>
                </label>
                <label className="block space-y-2 text-sm font-semibold text-fg">
                  <span>PDF title <span className="font-normal text-muted">(optional)</span></span>
                  <input type="text" value={title} maxLength={160} className={`${fieldClass} font-normal`} placeholder="Use the filename" onChange={(event) => {
                    setTitle(event.target.value);
                    updateDraft();
                  }} />
                </label>
              </div>
              {language === "other" && (
                <label className="block space-y-2 text-sm font-semibold text-fg">
                  <span>Language code</span>
                  <input required pattern="[A-Za-z]{2,3}" maxLength={3} placeholder="For example, it" className={`${fieldClass} font-normal`} value={customLanguage} onChange={(event) => {
                    setCustomLanguage(event.target.value);
                    updateDraft();
                  }} />
                </label>
              )}
            </div>
          ) : (
            <div className="mt-5 space-y-2">
              <label htmlFor="workflow-prompt" className="block text-sm font-semibold text-fg">Instruction</label>
              <textarea
                id="workflow-prompt"
                aria-describedby="workflow-prompt-hint"
                className={`${fieldClass} min-h-24 resize-y bg-surface-2`}
                rows={3}
                maxLength={500}
                value={prompt}
                placeholder="For example, compress this PDF and extract its text"
                onChange={(event) => { setPrompt(event.target.value); updateDraft(); }}
              />
              <p id="workflow-prompt-hint" className="text-xs leading-relaxed text-muted">SelfX uploads your file before drafting the steps. The planner receives your instruction and the file type.</p>
            </div>
          )}
        </fieldset>

        <section aria-labelledby="plan-heading" className="workspace-plan-panel flex min-w-0 flex-col rounded-2xl border border-ink-panel-line p-4 sm:p-6">
          <div className="flex items-center gap-2.5">
            <span className="grid size-9 place-items-center rounded-lg border border-ink-panel-line bg-ink-panel"><Workflow aria-hidden="true" className="size-4.5 text-ink-panel-accent" /></span>
            <h2 id="plan-heading" className="text-lg font-semibold tracking-tight">Workflow plan</h2>
          </div>
          {recording ? (
            <ol className="my-5 space-y-[1.15rem]">
              {RECORDING_STEPS.map(({ icon: Icon, title, description }, index) => (
                <li key={title} className="relative flex min-h-[3.4rem] items-center gap-3 rounded-lg border border-ink-panel-line bg-ink-panel px-3 py-2">
                  <Icon aria-hidden="true" className="size-4.5 shrink-0 text-ink-panel-accent" />
                  <div><p className="text-sm font-semibold">{title}</p><p className="text-xs leading-relaxed text-ink-panel-muted">{description}</p></div>
                  {index < RECORDING_STEPS.length - 1 && <ArrowDown aria-hidden="true" className="absolute bottom-[-1rem] left-4 z-10 size-3 text-ink-panel-muted" />}
                </li>
              ))}
            </ol>
          ) : plan ? (
            <div className="my-5 rounded-xl bg-surface p-3 text-fg">
              <p role="status" className="text-xs font-medium leading-relaxed text-primary">Draft ready. Edit your instruction to request different steps.</p>
              <WorkflowSteps plan={plan} />
              <Suspense fallback={null}><SaveRecipe plan={plan} /></Suspense>
            </div>
          ) : (
            <p className="my-5 rounded-xl border border-dashed border-ink-panel-line bg-ink-panel px-4 py-5 text-sm leading-relaxed text-ink-panel-muted">
              Your draft steps will appear here after you add a file and instruction.
            </p>
          )}

          <button
            type="submit"
            disabled={!ready || phase !== null}
            className="mt-auto inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-ink-panel-accent px-4 text-sm font-bold text-ink-panel transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-55"
          >
            {recording || plan ? <Play aria-hidden="true" className="size-4" /> : <Workflow aria-hidden="true" className="size-4" />}
            {action}
          </button>
          {phase && <span role="status" className="sr-only">{phase === "uploading" ? "Uploading file" : action}</span>}
          {error && <p role="alert" className="mt-3 break-words rounded-lg bg-ink-panel px-2 py-1 text-sm text-[#ffbcb2]">{error}</p>}
          <Link to="/jobs" className="mt-4 inline-flex items-center gap-1 self-start text-sm font-medium text-ink-panel-muted hover:text-ink-panel-text">
            View activity <ArrowRight aria-hidden="true" className="size-4" />
          </Link>
        </section>
      </form>

      <section aria-labelledby="starter-recipes" className="mt-9">
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h2 id="starter-recipes" className="text-lg font-semibold tracking-tight text-fg">Start with a recipe</h2>
          <Link to="/recipes" className="inline-flex shrink-0 items-center gap-1.5 text-sm font-semibold text-primary hover:underline">
            <BookOpen aria-hidden="true" className="hidden size-4 sm:block" />
            Browse recipes
          </Link>
        </div>
        <div className="grid gap-2.5 sm:grid-cols-3">
          {RECIPES.map(({ id, title, description, icon: Icon }) => (
            <Link key={id} to={`/recipes?recipe=${id}`}
              className="group flex min-w-0 items-start gap-3 rounded-xl border border-line bg-surface p-3.5 transition-colors hover:border-primary">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary-soft text-primary">
                <Icon aria-hidden="true" className="size-4.5" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold text-fg">{title}</span>
                <span className="mt-0.5 block text-xs leading-relaxed text-muted">{description}</span>
              </span>
              <ArrowRight aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted group-hover:text-primary" />
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
