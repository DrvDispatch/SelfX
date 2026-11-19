import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowLeft, ArrowRight, BookMarked, Captions, Download, FileStack, ImageDown,
  PencilLine, Play, ScanText, Trash2, Upload, Video,
} from "lucide-react";
import {
  ApiError, executeWorkflowPlan, getWorkflowCatalog, uploadFileWithProgress, type WorkflowAction,
} from "../api";
import { useAuth } from "../auth";
import { useConfirm } from "../components/ConfirmDialog";
import FileDrop from "../components/FileDrop";
import { useToast } from "../components/Toast";
import WorkflowSteps from "../components/WorkflowSteps";
import {
  checkRecipe, deleteRecipe, exportRecipe, importRecipe, newRecipeId, readSavedRecipes,
  RECIPE_CHANGED, RECIPE_FILE_LIMIT, recipeKey, renameRecipe, STARTER_RECIPES, type Recipe,
} from "../recipes";
import type { FileInfo } from "../types";

const secondary = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-surface px-3 text-sm font-medium text-fg transition-colors hover:bg-surface-2 disabled:opacity-50";
const primary = "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-fg transition-opacity hover:opacity-90 disabled:opacity-50";
const icons = {
  "creator-captions": Captions, "searchable-scan": ScanText, "web-image": ImageDown,
  "pdf-handoff": FileStack, "video-attachment": Video, "pdf-cover": FileStack,
};

function describeError(error: unknown): string {
  return error instanceof ApiError ? error.detail : error instanceof Error ? error.message : "Something went wrong.";
}

export default function Recipes() {
  const { user } = useAuth();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const fileInput = useRef<HTMLInputElement>(null);
  const userId = user?.id;
  const [saved, setSaved] = useState(() => userId ? readSavedRecipes(userId) : []);
  const [catalog, setCatalog] = useState<WorkflowAction[] | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [importError, setImportError] = useState<string | null>(null);

  useEffect(() => {
    const request = new AbortController();
    setCatalogError(null);
    getWorkflowCatalog(request.signal).then((actions) => {
      if (!request.signal.aborted) setCatalog(actions);
    }).catch((error: unknown) => {
      if (!request.signal.aborted) {
        setCatalog(null);
        setCatalogError(describeError(error));
      }
    });
    return () => request.abort();
  }, [revision]);

  useEffect(() => {
    if (!userId) return;
    const refresh = () => setSaved(readSavedRecipes(userId));
    const fromStorage = (event: StorageEvent) => { if (event.key === recipeKey(userId)) refresh(); };
    window.addEventListener(RECIPE_CHANGED, refresh);
    window.addEventListener("storage", fromStorage);
    refresh();
    return () => {
      window.removeEventListener(RECIPE_CHANGED, refresh);
      window.removeEventListener("storage", fromStorage);
    };
  }, [userId]);

  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file || !userId || !catalog) return;
    setImportError(null);
    try {
      if (file.size > RECIPE_FILE_LIMIT) throw new Error("A recipe file can be up to 64 KB.");
      const recipe = importRecipe(userId, await file.text(), catalog);
      toast.success(`Imported “${recipe.name}”.`);
      setParams({ recipe: recipe.id });
    } catch (error) {
      setImportError(describeError(error));
    }
  }

  const id = params.get("recipe");
  const picked = id ? [...STARTER_RECIPES, ...saved].find((recipe) => recipe.id === id) : undefined;
  const isSaved = !!picked && saved.some((recipe) => recipe.id === picked.id);
  const notice = catalogError && (
    <div role="status" className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface-2 p-3 text-sm text-muted">
      <span>Couldn’t check which recipe actions are available. {catalogError}</span>
      <button type="button" className={secondary} onClick={() => setRevision((value) => value + 1)}>Refresh actions</button>
    </div>
  );

  if (picked) {
    return (
      <div className="mx-auto max-w-5xl">
        <Link to="/recipes" className="mb-4 inline-flex min-h-9 items-center gap-2 text-sm font-medium text-muted hover:text-fg">
          <ArrowLeft aria-hidden="true" className="size-4" /> All recipes
        </Link>
        {notice}
        <RecipeRunner
          key={picked.id} recipe={picked} catalog={catalog} userId={isSaved ? userId : undefined}
          onRemove={() => setParams({})}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-6">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-fg sm:text-4xl">Recipes</h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted sm:text-base">
            Run a tested sequence of tools on a new file or save a workflow you want to repeat.
          </p>
        </div>
        <button type="button" disabled={!catalog} className={secondary} onClick={() => fileInput.current?.click()}>
          <Upload aria-hidden="true" className="size-4" /> Import recipe
        </button>
        <input
          ref={fileInput} type="file" aria-label="Choose a recipe file" className="hidden"
          accept=".json,application/json" onChange={(event) => void importFile(event)}
        />
      </header>
      <div className="mt-5">
        {notice}
        {id && <p role="status" className="mb-5 text-sm text-muted">This recipe isn’t in your library.</p>}
        {importError && <p role="alert" className="mb-5 text-sm text-danger">{importError}</p>}
      </div>
      <RecipeSection title="Starter recipes" recipes={STARTER_RECIPES} catalog={catalog} />
      <div className="mt-8">
        <RecipeSection title="Your recipes" recipes={saved} catalog={catalog} />
        {!saved.length && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed border-line bg-surface px-4 py-5">
            <p className="text-sm text-muted">Save a plan from Create or import a recipe file to start your library.</p>
            <Link className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:underline" to="/">
              Go to Create <ArrowRight aria-hidden="true" className="size-4" />
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}

function RecipeSection({ title, recipes, catalog }: { title: string; recipes: Recipe[]; catalog: WorkflowAction[] | null }) {
  return (
    <section aria-label={title}>
      <h2 className="mb-3 text-lg font-semibold tracking-tight text-fg">{title}</h2>
      {recipes.length > 0 && (
        <ul className="grid gap-3 sm:grid-cols-2">
          {recipes.map((recipe) => {
            const Icon = icons[recipe.id as keyof typeof icons] ?? BookMarked;
            const readiness = catalog ? checkRecipe(recipe.plan, catalog) : null;
            return (
              <li key={recipe.id}>
                <Link
                  to={`?recipe=${encodeURIComponent(recipe.id)}`}
                  className="group flex h-full items-start gap-3 rounded-xl border border-line bg-surface p-4 transition-colors hover:border-primary"
                >
                  <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary-soft text-primary">
                    <Icon aria-hidden="true" className="size-5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <span className="block break-words font-semibold text-fg">{recipe.name}</span>
                    {recipe.description && <span className="mt-1 block text-sm leading-relaxed text-muted">{recipe.description}</span>}
                    <span className="mt-2 block text-xs text-muted">
                      {recipe.plan.steps.length === 1 ? "1 step" : `${recipe.plan.steps.length} steps`}
                      {readiness?.reason && " · Action unavailable"}
                    </span>
                  </div>
                  <ArrowRight aria-hidden="true" className="size-4 shrink-0 text-faint transition-colors group-hover:text-primary" />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function RecipeRunner({
  recipe, catalog, userId, onRemove,
}: { recipe: Recipe; catalog: WorkflowAction[] | null; userId?: string; onRemove: () => void }) {
  const navigate = useNavigate();
  const toast = useToast();
  const confirm = useConfirm();
  const mounted = useRef(true);
  const pending = useRef(false);
  const key = useRef<string | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [uploaded, setUploaded] = useState<FileInfo | null>(null);
  const [phase, setPhase] = useState<"uploading" | "starting" | null>(null);
  const [percent, setPercent] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(recipe.name);
  const ready = catalog ? checkRecipe(recipe.plan, catalog) : null;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  async function start(event: FormEvent) {
    event.preventDefault();
    if (!files[0] || !ready?.extensions.length || pending.current) return;
    pending.current = true;
    setError(null);
    try {
      let attachment = uploaded;
      if (!attachment) {
        setPhase("uploading");
        setPercent(0);
        attachment = await uploadFileWithProgress(files[0], (value) => {
          if (mounted.current) setPercent(value);
        });
        if (!mounted.current) return;
        setUploaded(attachment);
      }
      setPhase("starting");
      key.current ??= newRecipeId();
      const job = await executeWorkflowPlan(attachment.id, recipe.plan, key.current);
      if (!mounted.current) return;
      toast.success("Workflow queued. You can follow it in Activity.");
      navigate(`/runs/${job.id}`);
    } catch (failure) {
      if (!mounted.current) return;
      if (failure instanceof ApiError && [404, 410].includes(failure.status)) {
        setUploaded(null);
        key.current = null;
      }
      setError(describeError(failure));
    } finally {
      pending.current = false;
      if (mounted.current) setPhase(null);
    }
  }

  async function remove() {
    if (!userId || !(await confirm({
      title: "Remove saved recipe?",
      message: `“${recipe.name}” will be removed from this browser’s library.`,
      confirmLabel: "Remove recipe", cancelLabel: "Keep recipe", danger: true,
    }))) return;
    try {
      deleteRecipe(userId, recipe.id);
      toast.success("Recipe removed.");
      onRemove();
    } catch (failure) {
      setSaveError(describeError(failure));
    }
  }

  function rename(event: FormEvent) {
    event.preventDefault();
    if (!userId) return;
    try {
      renameRecipe(userId, recipe.id, name);
      setEditing(false);
      setSaveError(null);
      toast.success("Recipe renamed.");
    } catch (failure) {
      setSaveError(describeError(failure));
    }
  }

  return (
    <div>
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="break-words text-3xl font-semibold tracking-tight text-fg">{recipe.name}</h1>
          {recipe.description && <p className="mt-2 text-sm text-muted">{recipe.description}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={secondary} onClick={() => exportRecipe(recipe)}>
            <Download aria-hidden="true" className="size-4" /> Export recipe
          </button>
          {userId && <>
            <button type="button" className={secondary} onClick={() => { setName(recipe.name); setSaveError(null); setEditing(true); }}>
              <PencilLine aria-hidden="true" className="size-4" /> Rename
            </button>
            <button type="button" className={secondary} onClick={() => void remove()}>
              <Trash2 aria-hidden="true" className="size-4" /> Remove
            </button>
          </>}
        </div>
      </header>
      {editing && (
        <form className="mb-4 flex flex-wrap items-end gap-2 rounded-xl border border-line bg-surface p-4" onSubmit={rename}>
          <label className="flex min-w-44 flex-1 flex-col gap-1 text-sm font-medium text-fg">
            Recipe name
            <input autoFocus maxLength={64} value={name} onChange={(event) => setName(event.target.value)}
              className="min-h-10 rounded-lg border border-line bg-surface px-3 text-sm text-fg" />
          </label>
          <button type="submit" className={secondary} disabled={!name.trim()}>Save name</button>
          <button type="button" className={secondary} onClick={() => { setEditing(false); setSaveError(null); }}>Cancel</button>
        </form>
      )}
      {saveError && <p role="alert" className="mb-4 text-sm text-danger">{saveError}</p>}
      <div className="grid items-start gap-4 lg:grid-cols-[1.15fr_1fr]">
        <section className="min-w-0 rounded-xl border border-line bg-surface p-4 sm:p-5" aria-label="Review steps">
          <h2 className="text-lg font-semibold text-fg">Review steps</h2>
          <WorkflowSteps plan={recipe.plan} />
        </section>
        <form className="min-w-0 rounded-xl border border-line bg-surface p-4 sm:p-5" onSubmit={(event) => void start(event)}>
          <h2 className="text-lg font-semibold text-fg">Choose a source file</h2>
          {!ready && <p className="mt-2 text-sm text-muted">Checking installed actions…</p>}
          {ready?.reason && <p role="status" className="mt-2 text-sm text-muted">{ready.reason}</p>}
          {!!ready?.extensions.length && (
            <div className="mt-3">
              <FileDrop accepts={ready.extensions} files={files} multiple={false} disabled={phase !== null} onChange={(items) => {
                setFiles(items); setUploaded(null); key.current = null; setError(null);
              }} />
            </div>
          )}
          {phase === "uploading" && <progress className="mt-3 w-full accent-primary" value={percent} max={1} aria-label="Upload progress" />}
          {error && <p role="alert" className="mt-3 break-words text-sm text-danger">{error}</p>}
          <button className={`${primary} mt-4`} type="submit" disabled={!files[0] || !ready?.extensions.length || phase !== null}>
            <Play aria-hidden="true" className="size-4" />
            {phase === "uploading" ? "Uploading…" : phase === "starting" ? "Queueing…" : "Run recipe"}
          </button>
        </form>
      </div>
    </div>
  );
}
