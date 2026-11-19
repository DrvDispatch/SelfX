import { useId, useState } from "react";
import { BookmarkPlus } from "lucide-react";
import { ApiError, getWorkflowCatalog, type WorkflowPlan } from "../api";
import { useAuth } from "../auth";
import { saveRecipe } from "../recipes";
import { useToast } from "./Toast";

export default function SaveRecipe({ plan, suggestedName }: { plan: WorkflowPlan; suggestedName?: string }) {
  const { user } = useAuth();
  const toast = useToast();
  const inputId = useId();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(suggestedName?.slice(0, 64) ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!user || busy || !name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const catalog = await getWorkflowCatalog();
      const recipe = saveRecipe(user.id, { name, plan }, catalog);
      toast.success(`Saved “${recipe.name}” to Recipes.`);
      setOpen(false);
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.detail : failure instanceof Error ? failure.message : "Could not save the recipe.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line px-3 text-sm font-medium text-primary transition-colors hover:bg-surface-2"
        onClick={() => { setError(null); setOpen(true); }}
      >
        <BookmarkPlus aria-hidden="true" className="size-4" /> Save as recipe
      </button>
    );
  }

  return (
    <div className="w-full rounded-xl border border-line bg-surface-2 p-3 text-left sm:p-4">
      <label className="block text-sm font-medium text-fg" htmlFor={inputId}>Recipe name</label>
      <p className="mt-1 text-xs text-muted">Save these steps and settings in this browser for your account.</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <input
          autoFocus
          aria-describedby={error ? `${inputId}-error` : undefined}
          id={inputId}
          value={name}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") { event.preventDefault(); void save(); }
            if (event.key === "Escape" && !busy) setOpen(false);
          }}
          disabled={busy}
          maxLength={64}
          placeholder="E.g. Monthly report export"
          className="min-h-10 min-w-36 flex-1 rounded-lg border border-line bg-surface px-3 text-sm text-fg placeholder:text-muted"
        />
        <button
          type="button" disabled={busy || !name.trim()} onClick={() => void save()}
          className="min-h-10 rounded-lg bg-primary px-3 text-sm font-semibold text-primary-fg disabled:opacity-50"
        >
          {busy ? "Saving…" : "Save recipe"}
        </button>
        <button
          type="button" disabled={busy} onClick={() => setOpen(false)}
          className="min-h-10 rounded-lg px-2 text-sm font-medium text-muted hover:text-fg"
        >
          Cancel
        </button>
      </div>
      {error && <p id={`${inputId}-error`} role="alert" className="mt-2 text-sm text-danger">{error}</p>}
    </div>
  );
}
