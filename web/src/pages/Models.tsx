import { useEffect, useRef, useState } from "react";
import { Boxes, Download, Loader2, Trash2 } from "lucide-react";
import { ApiError, deleteModel, listModels, pullModel, type OllamaModel } from "../api";
import { RowsSkeleton } from "../components/Skeleton";
import HardwarePreflight from "../components/HardwarePreflight";
import { useToast } from "../components/Toast";
import { useConfirm } from "../components/ConfirmDialog";
import { formatBytes } from "../format";

const SUGGESTIONS = ["qwen3:8b", "llama3.2:3b", "moondream", "nomic-embed-text", "bge-m3", "gemma3:4b"];

export default function Models() {
  const toast = useToast();
  const confirm = useConfirm();
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [pulling, setPulling] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const pullInput = useRef<HTMLInputElement>(null);

  const refresh = () =>
    listModels()
      .then((r) => { setModels(r.models); setPulling(r.pulling); setError(null); })
      .catch((e) => setError(e instanceof Error ? e.message : "failed"))
      .finally(() => setLoading(false));

  useEffect(() => { void refresh(); }, []);
  useEffect(() => {
    if (pulling.length === 0) return;
    const t = setTimeout(() => void refresh(), 3000);
    return () => clearTimeout(t);
  }, [pulling]);

  const pull = async (n: string) => {
    const m = n.trim();
    if (!m) return;
    try {
      await pullModel(m);
      setName("");
      toast.info(`Pulling “${m}” — this can take a while`);
      void refresh();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Couldn't start the pull");
    }
  };
  const remove = async (n: string) => {
    if (!(await confirm({ title: `Delete model “${n}”?`, message: "It will be removed from disk; you can re-pull it later.", danger: true, confirmLabel: "Delete" }))) return;
    try {
      await deleteModel(n);
      toast.success(`Model “${n}” deleted`);
      void refresh();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Couldn't delete the model");
    }
  };

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6 flex items-center gap-2.5">
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-primary-soft"><Boxes className="h-5 w-5 text-primary" /></span>
        <div>
          <h1 className="text-xl font-bold text-fg">AI Models</h1>
          <p className="text-sm text-muted">Manage the local Ollama models powering the AI tools & agent.</p>
        </div>
      </div>

      <HardwarePreflight onUseModel={(model) => {
        setName(model);
        pullInput.current?.focus();
      }} />

      {error && <p className="mb-4 rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-danger">{error}</p>}

      <div className="mb-4 flex gap-2">
        <input ref={pullInput} aria-label="Model name to pull" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void pull(name)}
               placeholder="Pull a model, e.g. qwen3:8b"
               className="flex-1 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5 text-sm text-fg outline-none placeholder:text-faint focus:border-primary" />
        <button onClick={() => void pull(name)} className="flex items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-fg hover:opacity-90">
          <Download className="h-4 w-4" /> Pull
        </button>
      </div>
      <div className="mb-6 flex flex-wrap gap-1.5">
        {SUGGESTIONS.map((s) => (
          <button key={s} onClick={() => void pull(s)} className="rounded-full bg-surface-2 px-2.5 py-1 text-xs text-muted hover:text-fg">+ {s}</button>
        ))}
      </div>

      {pulling.length > 0 && (
        <div className="mb-4 space-y-1">
          {pulling.map((p) => (
            <div key={p} className="flex items-center gap-2 rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-fg">
              <Loader2 className="h-4 w-4 animate-spin text-primary" /> pulling <span className="font-medium">{p}</span>…
            </div>
          ))}
        </div>
      )}

      {loading ? (
        <RowsSkeleton count={3} />
      ) : (
      <div className="divide-y divide-line rounded-2xl border border-line bg-surface">
        {models.length === 0 && <p className="p-4 text-sm text-muted">No models installed yet — pull one above.</p>}
        {models.map((m) => (
          <div key={m.name} className="flex items-center gap-3 px-4 py-3">
            <div className="min-w-0 flex-1">
              <span className="block truncate font-medium text-fg">{m.name}</span>
              <span className="text-xs text-faint">
                {formatBytes(m.size)}{m.details?.parameter_size ? ` · ${m.details.parameter_size}` : ""}
                {m.details?.quantization_level ? ` · ${m.details.quantization_level}` : ""}
              </span>
            </div>
            <button onClick={() => void remove(m.name)} className="grid h-8 w-8 place-items-center rounded-full text-faint hover:bg-surface-2 hover:text-danger">
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
      )}
    </div>
  );
}
