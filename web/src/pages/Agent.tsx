import { useEffect, useRef, useState } from "react";
import { Bot, Cpu, Eye, Loader2, Paperclip, Send, Sparkles, User, Wrench, X } from "lucide-react";
import {
  agentChat,
  agentStatus,
  uploadFile,
  type AgentStatus,
  type AgentStep,
} from "../api";
import FilePreview, { type PreviewFile } from "../components/FilePreview";
import { formatBytes } from "../format";

interface Turn {
  role: "user" | "assistant";
  content: string;
  steps?: AgentStep[];
}

function StepCard({ step }: { step: AgentStep }) {
  const [preview, setPreview] = useState<PreviewFile | null>(null);
  const outs = step.result?.outputs ?? [];
  const ok = step.result?.ok !== false && step.result?.error === undefined;
  return (
    <div className="rounded-xl border border-line bg-surface-2 p-2.5 text-sm">
      <div className="flex items-center gap-2">
        <Wrench className="h-4 w-4 text-primary" />
        <span className="font-medium text-fg">{step.tool}</span>
        <span className={`ml-auto text-xs ${ok ? "text-ok" : "text-danger"}`}>
          {step.result?.status ?? (ok ? "done" : "failed")}
        </span>
      </div>
      {step.result?.error && <p className="mt-1 text-xs text-danger">{String(step.result.error)}</p>}
      {outs.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {outs.map((o) => (
            <button
              key={o.id}
              onClick={() => setPreview({ id: o.id, orig_name: o.name, mime: "" })}
              className="flex items-center gap-1 rounded-full bg-surface px-2.5 py-1 text-xs text-primary hover:bg-line"
            >
              <Eye className="h-3.5 w-3.5" /> {o.name} <span className="text-faint">({formatBytes(o.size)})</span>
            </button>
          ))}
        </div>
      )}
      {preview && <FilePreview file={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}

export default function Agent() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [provider, setProvider] = useState<string>("ollama");
  const fileRef = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    agentStatus().then((s) => {
      setStatus(s);
      setProvider(s.default_provider);
    }).catch(() => undefined);
  }, []);
  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [turns, busy]);

  const send = async () => {
    const msg = input.trim();
    if (!msg || busy) return;
    setBusy(true);
    setTurns((t) => [...t, { role: "user", content: msg }]);
    setInput("");
    try {
      const fileIds: string[] = [];
      for (const f of files) fileIds.push((await uploadFile(f)).id);
      setFiles([]);
      const reply = await agentChat(msg, fileIds, provider);
      setTurns((t) => [...t, { role: "assistant", content: reply.answer, steps: reply.steps }]);
    } catch (e) {
      setTurns((t) => [...t, { role: "assistant", content: `Error: ${e instanceof Error ? e.message : "failed"}` }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex h-[calc(100vh-9rem)] max-w-3xl flex-col">
      <div className="mb-3 flex items-center gap-2">
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-primary-soft">
          <Sparkles className="h-5 w-5 text-primary" />
        </span>
        <div className="mr-auto">
          <h1 className="font-bold text-fg">Assistant</h1>
          <p className="text-xs text-muted">Ask in plain language — I&apos;ll use your tools. Files stay local.</p>
        </div>
        {/* provider toggle */}
        <div className="flex rounded-full bg-surface-2 p-0.5 text-xs">
          <button
            onClick={() => setProvider("ollama")}
            className={`flex items-center gap-1 rounded-full px-2.5 py-1 ${provider === "ollama" ? "bg-primary text-primary-fg" : "text-muted"}`}
          >
            <Cpu className="h-3.5 w-3.5" /> Local
          </button>
          <button
            onClick={() => status?.gemini_available && setProvider("gemini")}
            disabled={!status?.gemini_available}
            title={status?.gemini_available ? "Gemini" : "Set GEMINI_API_KEY to enable"}
            className={`flex items-center gap-1 rounded-full px-2.5 py-1 disabled:opacity-40 ${provider === "gemini" ? "bg-primary text-primary-fg" : "text-muted"}`}
          >
            <Sparkles className="h-3.5 w-3.5" /> Gemini
          </button>
        </div>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto rounded-2xl border border-line bg-surface p-4">
        {turns.length === 0 && (
          <div className="grid h-full place-items-center text-center text-sm text-muted">
            <div>
              <Bot className="mx-auto mb-2 h-8 w-8 text-faint" />
              Try: &quot;make a QR code for my website&quot; · &quot;compress this PDF&quot; ·
              &quot;transcribe this audio and summarize it&quot;
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={`flex gap-2.5 ${t.role === "user" ? "flex-row-reverse" : ""}`}>
            <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-full ${t.role === "user" ? "bg-surface-2" : "bg-primary-soft"}`}>
              {t.role === "user" ? <User className="h-4 w-4 text-muted" /> : <Bot className="h-4 w-4 text-primary" />}
            </span>
            <div className={`max-w-[80%] space-y-2 ${t.role === "user" ? "text-right" : ""}`}>
              {t.steps && t.steps.length > 0 && (
                <div className="space-y-1.5">{t.steps.map((s, j) => <StepCard key={j} step={s} />)}</div>
              )}
              <div className={`inline-block whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm ${t.role === "user" ? "bg-primary text-primary-fg" : "bg-surface-2 text-fg"}`}>
                {t.content}
              </div>
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex items-center gap-2 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> working…
          </div>
        )}
        <div ref={endRef} />
      </div>

      {files.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {files.map((f, i) => (
            <span key={i} className="flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-1 text-xs text-fg">
              {f.name}
              <button onClick={() => setFiles((x) => x.filter((_, j) => j !== i))} className="text-faint hover:text-danger">
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="mt-2 flex items-end gap-2">
        <button
          onClick={() => fileRef.current?.click()}
          className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-surface-2 text-muted hover:bg-line hover:text-fg"
          title="Attach files"
        >
          <Paperclip className="h-5 w-5" />
          <input ref={fileRef} type="file" multiple className="hidden"
                 onChange={(e) => { if (e.target.files) setFiles((x) => [...x, ...Array.from(e.target.files!)]); e.target.value = ""; }} />
        </button>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }}
          placeholder="Ask me to do something with your files…"
          rows={1}
          className="max-h-32 flex-1 resize-none rounded-xl border border-line bg-surface-2 px-3.5 py-2.5 text-sm text-fg outline-none placeholder:text-faint focus:border-primary"
        />
        <button
          onClick={() => void send()}
          disabled={busy || !input.trim()}
          className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary text-primary-fg hover:opacity-90 disabled:opacity-50"
        >
          <Send className="h-5 w-5" />
        </button>
      </div>
    </div>
  );
}
