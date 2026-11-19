import { useEffect, useRef, useState } from "react";
import { Bot, Check, Copy, Cpu, Eye, Loader2, Paperclip, Send, Sparkles, Trash2, User, Wrench } from "lucide-react";
import {
  ApiError,
  agentChat,
  agentStatus,
  uploadFileWithProgress,
  type AgentStatus,
  type AgentStep,
} from "../api";
import FilePreview, { type PreviewFile } from "../components/FilePreview";
import FileChip, { type UploadItem } from "../components/FileChip";
import Markdown from "../components/Markdown";
import { useToast } from "../components/Toast";

interface Turn {
  role: "user" | "assistant";
  content: string;
  steps?: AgentStep[];
  files?: string[];
}

const EXAMPLES = [
  "Make a QR code for https://example.com",
  "Compress this PDF",
  "Transcribe this audio and summarize it",
  "Remove the background from this image",
];

function StepCard({ step }: { step: AgentStep }) {
  const [preview, setPreview] = useState<PreviewFile | null>(null);
  const outs = step.result?.outputs ?? [];
  const ok = step.result?.ok !== false && !step.result?.error;
  return (
    <div className="rounded-xl border border-line bg-surface-2 p-2.5 text-sm">
      <div className="flex items-center gap-2">
        <Wrench className="h-4 w-4 text-primary" />
        <span className="font-medium text-fg">{step.tool}</span>
        <span className={`ml-auto rounded-full px-2 py-0.5 text-[11px] font-medium ${ok ? "bg-ok/10 text-ok" : "bg-danger/10 text-danger"}`}>
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
              className="flex items-center gap-1 rounded-full bg-surface px-2.5 py-1 text-xs text-primary transition-colors hover:bg-line"
            >
              <Eye className="h-3.5 w-3.5" /> {o.name}
            </button>
          ))}
        </div>
      )}
      {preview && <FilePreview file={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}

function AssistantBubble({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };
  return (
    <div className="group/bubble relative inline-block max-w-full rounded-2xl bg-surface-2 px-3.5 py-2">
      <Markdown content={content} />
      <button
        onClick={() => void copy()}
        title="Copy"
        className="absolute -right-1 -top-1 grid h-6 w-6 place-items-center rounded-full border border-line bg-surface text-faint opacity-0 transition-opacity hover:text-fg group-hover/bubble:opacity-100"
      >
        {copied ? <Check className="h-3 w-3 text-ok" /> : <Copy className="h-3 w-3" />}
      </button>
    </div>
  );
}

let keySeq = 0;

export default function Agent() {
  const toast = useToast();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [attached, setAttached] = useState<UploadItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [provider, setProvider] = useState<string>("ollama");
  const fileRef = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    agentStatus()
      .then((s) => { setStatus(s); setProvider(s.default_provider); })
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth";
    endRef.current?.scrollIntoView({ behavior, block: "nearest" });
  }, [turns, busy]);

  const addFiles = (list: FileList | File[]) => {
    const items: UploadItem[] = Array.from(list).map((file) => ({
      key: `f${++keySeq}`, file, progress: 0, status: "pending",
    }));
    setAttached((a) => [...a, ...items]);
  };

  const removeAttached = (key: string) => setAttached((a) => a.filter((x) => x.key !== key));

  const patch = (key: string, p: Partial<UploadItem>) =>
    setAttached((a) => a.map((x) => (x.key === key ? { ...x, ...p } : x)));

  const send = async () => {
    const msg = input.trim();
    if (!msg || busy) return;
    setBusy(true);
    const toUpload = attached;
    const names = toUpload.map((f) => f.file.name);
    try {
      // Upload each attachment with live progress before sending.
      const fileIds: string[] = [];
      for (const item of toUpload) {
        if (item.id) {
          fileIds.push(item.id);
          continue;
        }
        patch(item.key, { status: "uploading", progress: 0 });
        try {
          const info = await uploadFileWithProgress(item.file, (frac) => patch(item.key, { progress: frac }));
          patch(item.key, { status: "done", progress: 1, id: info.id });
          fileIds.push(info.id);
        } catch (e) {
          const detail = e instanceof ApiError ? e.detail : "upload failed";
          patch(item.key, { status: "error", error: detail });
          throw new Error(`Couldn't upload ${item.file.name}: ${detail}`);
        }
      }
      const reply = await agentChat(msg, fileIds, provider);
      setTurns((t) => [
        ...t,
        { role: "user", content: msg, files: names },
        { role: "assistant", content: reply.answer, steps: reply.steps },
      ]);
      setInput("");
      setAttached((files) => files.filter((file) => !toUpload.some((item) => item.key === file.key)));
    } catch (e) {
      const m = e instanceof Error ? e.message : "The assistant request failed";
      toast.error(m);
    } finally {
      setBusy(false);
    }
  };

  const uploading = attached.some((a) => a.status === "uploading");
  const canSend = !busy && input.trim().length > 0;

  return (
    <div className="mx-auto flex h-[calc(100dvh-8rem)] max-w-3xl flex-col">
      <div className="mb-3 flex items-center gap-2">
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-primary-soft">
          <Sparkles className="h-5 w-5 text-primary" />
        </span>
        <div className="mr-auto">
          <h1 className="font-bold text-fg">Assistant</h1>
          <p className="text-xs text-muted">{provider === "gemini" ? "Gemini receives prompts and tool context." : "Your server handles model requests and file processing."}</p>
        </div>
        {turns.length > 0 && (
          <button
            onClick={() => setTurns([])}
            title="Clear conversation"
            className="grid h-8 w-8 place-items-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-danger"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        )}
        <div className="flex rounded-full bg-surface-2 p-0.5 text-xs">
          <button
            onClick={() => setProvider("ollama")}
            className={`flex items-center gap-1 rounded-full px-2.5 py-1 transition-colors ${provider === "ollama" ? "bg-primary text-primary-fg" : "text-muted hover:text-fg"}`}
          >
            <Cpu className="h-3.5 w-3.5" /> Local
          </button>
          <button
            onClick={() => (status?.gemini_available ? setProvider("gemini") : toast.info("Set GEMINI_API_KEY to enable Gemini"))}
            title={status?.gemini_available ? "Gemini" : "Set GEMINI_API_KEY to enable"}
            className={`flex items-center gap-1 rounded-full px-2.5 py-1 transition-colors ${provider === "gemini" ? "bg-primary text-primary-fg" : "text-muted hover:text-fg"} ${status?.gemini_available ? "" : "opacity-40"}`}
          >
            <Sparkles className="h-3.5 w-3.5" /> Gemini
          </button>
        </div>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto rounded-2xl border border-line bg-surface p-4">
        {turns.length === 0 && (
          <div className="grid h-full place-items-center text-center">
            <div className="max-w-md">
              <span className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-primary-soft">
                <Bot className="h-6 w-6 text-primary" />
              </span>
              <p className="mb-4 text-sm text-muted">Try one of these, or attach a file and tell me what to do:</p>
              <div className="flex flex-wrap justify-center gap-2">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    onClick={() => { setInput(ex); taRef.current?.focus(); }}
                    className="rounded-full border border-line bg-surface-2 px-3 py-1.5 text-xs text-fg transition-colors hover:border-primary hover:text-primary"
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={`animate-in flex gap-2.5 ${t.role === "user" ? "flex-row-reverse" : ""}`}>
            <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-full ${t.role === "user" ? "bg-surface-2" : "bg-primary-soft"}`}>
              {t.role === "user" ? <User className="h-4 w-4 text-muted" /> : <Bot className="h-4 w-4 text-primary" />}
            </span>
            <div className={`max-w-[82%] space-y-2 ${t.role === "user" ? "flex flex-col items-end" : ""}`}>
              {t.steps && t.steps.length > 0 && (
                <div className="w-full space-y-1.5">{t.steps.map((s, j) => <StepCard key={j} step={s} />)}</div>
              )}
              {t.role === "assistant" ? (
                t.content && <AssistantBubble content={t.content} />
              ) : (
                <>
                  {t.files && t.files.length > 0 && (
                    <div className="flex flex-wrap justify-end gap-1">
                      {t.files.map((n) => (
                        <span key={n} className="flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-muted">
                          <Paperclip className="h-3 w-3" /> {n}
                        </span>
                      ))}
                    </div>
                  )}
                  {t.content && (
                    <div className="inline-block whitespace-pre-wrap rounded-2xl bg-primary px-3.5 py-2 text-sm text-primary-fg">
                      {t.content}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        ))}
        {busy && !uploading && (
          <div className="flex items-center gap-2 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Thinking…
          </div>
        )}
        <div ref={endRef} />
      </div>

      {attached.length > 0 && (
        <div className="mt-2 flex flex-col gap-1.5">
          {attached.map((item) => (
            <FileChip
              key={item.key}
              item={item}
              disabled={busy}
              onRemove={item.status === "uploading" ? undefined : () => removeAttached(item.key)}
            />
          ))}
        </div>
      )}

      <div className="mt-2 flex items-end gap-2">
        <button
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-surface-2 text-muted transition-colors hover:bg-line hover:text-fg disabled:opacity-50"
          title="Attach files"
        >
          <Paperclip className="h-5 w-5" />
          <input
            ref={fileRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }}
          />
        </button>
        <textarea
          ref={taRef}
          disabled={busy}
          aria-label="Message"
          maxLength={4000}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }}
          onPaste={(e) => {
            const imgs = Array.from(e.clipboardData.items)
              .filter((it) => it.kind === "file" && it.type.startsWith("image/"))
              .map((it) => it.getAsFile())
              .filter((f): f is File => f !== null);
            if (imgs.length) { e.preventDefault(); addFiles(imgs); }
          }}
          placeholder="Ask me to do something with your files…"
          rows={1}
          className="max-h-32 flex-1 resize-none rounded-xl border border-line bg-surface-2 px-3.5 py-2.5 text-sm text-fg outline-none transition-colors placeholder:text-faint focus:border-primary"
        />
        <button
          onClick={() => void send()}
          disabled={!canSend}
          className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary text-primary-fg transition-opacity hover:opacity-90 disabled:opacity-50"
          title="Send"
        >
          {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
        </button>
      </div>
    </div>
  );
}
