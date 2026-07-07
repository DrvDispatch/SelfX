import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, FileText, Loader2, Plus, Send, Trash2, Upload } from "lucide-react";
import {
  kbAddDocuments,
  kbChat,
  kbCreateCollection,
  kbDeleteCollection,
  kbListCollections,
  kbListDocuments,
  kbMessages,
  uploadFile,
  type Citation,
  type KbCollection,
  type KbDocument,
} from "../api";

interface Msg { role: string; content: string; citations: Citation[]; }

export default function KnowledgeBase() {
  const [cols, setCols] = useState<KbCollection[]>([]);
  const [sel, setSel] = useState<KbCollection | null>(null);
  const [docs, setDocs] = useState<KbDocument[]>([]);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const refreshCols = useCallback(() => kbListCollections().then(setCols).catch(() => undefined), []);
  useEffect(() => { void refreshCols(); }, [refreshCols]);

  const openCollection = useCallback((c: KbCollection) => {
    setSel(c);
    setMsgs([]);
    kbListDocuments(c.id).then(setDocs).catch(() => undefined);
    kbMessages(c.id).then((m) => setMsgs(m)).catch(() => undefined);
  }, []);

  // poll doc statuses while any are still indexing
  useEffect(() => {
    if (!sel) return;
    if (!docs.some((d) => d.status === "pending" || d.status === "indexing")) return;
    const t = setTimeout(() => {
      kbListDocuments(sel.id).then(setDocs).catch(() => undefined);
      void refreshCols();
    }, 2000);
    return () => clearTimeout(t);
  }, [sel, docs, refreshCols]);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [msgs, busy]);

  const create = async () => {
    if (!newName.trim()) return;
    const c = await kbCreateCollection(newName.trim());
    setNewName("");
    await refreshCols();
    openCollection(c);
  };

  const addFiles = async (fl: FileList | File[]) => {
    if (!sel) return;
    setBusy(true);
    try {
      const ids: string[] = [];
      for (const f of Array.from(fl)) ids.push((await uploadFile(f)).id);
      const added = await kbAddDocuments(sel.id, ids);
      setDocs((d) => [...d, ...added]);
    } finally {
      setBusy(false);
    }
  };

  const ask = async () => {
    const question = q.trim();
    if (!question || !sel || busy) return;
    setBusy(true);
    setMsgs((m) => [...m, { role: "user", content: question, citations: [] }]);
    setQ("");
    try {
      const r = await kbChat(sel.id, question);
      setMsgs((m) => [...m, { role: "assistant", content: r.answer, citations: r.citations }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "assistant", content: `Error: ${e instanceof Error ? e.message : "failed"}`, citations: [] }]);
    } finally {
      setBusy(false);
    }
  };

  const del = async (c: KbCollection) => {
    await kbDeleteCollection(c.id);
    if (sel?.id === c.id) setSel(null);
    await refreshCols();
  };

  return (
    <div className="grid h-[calc(100vh-9rem)] grid-cols-[16rem_1fr] gap-4">
      {/* collections sidebar */}
      <aside className="flex flex-col gap-2 overflow-y-auto rounded-2xl border border-line bg-surface p-3">
        <div className="flex items-center gap-2 px-1">
          <BookOpen className="h-4 w-4 text-primary" />
          <span className="font-semibold text-fg">Collections</span>
        </div>
        <div className="flex gap-1">
          <input value={newName} onChange={(e) => setNewName(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && void create()}
                 placeholder="New collection…"
                 className="min-w-0 flex-1 rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-sm text-fg outline-none placeholder:text-faint focus:border-primary" />
          <button onClick={() => void create()} className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary text-primary-fg hover:opacity-90">
            <Plus className="h-4 w-4" />
          </button>
        </div>
        {cols.map((c) => (
          <div key={c.id} className={`group flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm ${sel?.id === c.id ? "bg-primary-soft" : "hover:bg-surface-2"}`}>
            <button onClick={() => openCollection(c)} className="min-w-0 flex-1 text-left">
              <span className="block truncate font-medium text-fg">{c.name}</span>
              <span className="block text-xs text-faint">{c.documents} docs · {c.chunks} chunks</span>
            </button>
            <button onClick={() => void del(c)} className="shrink-0 text-faint opacity-0 hover:text-danger group-hover:opacity-100">
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
        {cols.length === 0 && <p className="px-1 text-xs text-muted">No collections yet. Create one to start.</p>}
      </aside>

      {/* main */}
      {!sel ? (
        <div className="grid place-items-center rounded-2xl border border-line bg-surface text-sm text-muted">
          Select or create a collection, add documents, and chat with them.
        </div>
      ) : (
        <div className="flex flex-col gap-3 overflow-hidden">
          {/* documents strip */}
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files.length) void addFiles(e.dataTransfer.files); }}
            className="shrink-0 rounded-2xl border border-line bg-surface p-3"
          >
            <div className="mb-2 flex items-center gap-2">
              <span className="font-semibold text-fg">{sel.name}</span>
              <button onClick={() => fileRef.current?.click()} className="ml-auto flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-1 text-xs text-fg hover:bg-line">
                <Upload className="h-3.5 w-3.5" /> Add documents
              </button>
              <input ref={fileRef} type="file" multiple className="hidden"
                     accept=".pdf,.txt,.md,.markdown,.docx"
                     onChange={(e) => { if (e.target.files) void addFiles(e.target.files); e.target.value = ""; }} />
            </div>
            <div className="flex flex-wrap gap-2">
              {docs.length === 0 && <p className="text-xs text-muted">Drop PDF / DOCX / TXT / MD here, or click “Add documents”.</p>}
              {docs.map((d) => (
                <span key={d.id} className="flex items-center gap-1.5 rounded-full bg-surface-2 px-2.5 py-1 text-xs" title={d.error ?? ""}>
                  <FileText className="h-3.5 w-3.5 text-faint" />
                  <span className="text-fg">{d.orig_name}</span>
                  {d.status === "indexed"
                    ? <span className="text-ok">✓ {d.n_chunks}</span>
                    : d.status === "error"
                      ? <span className="text-danger">error</span>
                      : <Loader2 className="h-3 w-3 animate-spin text-primary" />}
                </span>
              ))}
            </div>
          </div>

          {/* chat */}
          <div className="flex-1 space-y-3 overflow-y-auto rounded-2xl border border-line bg-surface p-4">
            {msgs.length === 0 && <p className="text-sm text-muted">Ask a question about this collection.</p>}
            {msgs.map((m, i) => (
              <div key={i} className={m.role === "user" ? "text-right" : ""}>
                <div className={`inline-block max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm ${m.role === "user" ? "bg-primary text-primary-fg" : "bg-surface-2 text-fg"}`}>
                  {m.content}
                </div>
                {m.citations.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {m.citations.map((c) => (
                      <span key={c.n} title={c.snippet}
                            className="rounded-full border border-line bg-surface px-2 py-0.5 text-[11px] text-muted">
                        [{c.n}] {c.document}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {busy && <div className="flex items-center gap-2 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin" /> thinking…</div>}
            <div ref={endRef} />
          </div>

          <div className="flex items-end gap-2">
            <textarea value={q} onChange={(e) => setQ(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask(); } }}
                      placeholder="Ask this collection…" rows={1}
                      className="max-h-32 flex-1 resize-none rounded-xl border border-line bg-surface-2 px-3.5 py-2.5 text-sm text-fg outline-none placeholder:text-faint focus:border-primary" />
            <button onClick={() => void ask()} disabled={busy || !q.trim()}
                    className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary text-primary-fg hover:opacity-90 disabled:opacity-50">
              <Send className="h-5 w-5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
