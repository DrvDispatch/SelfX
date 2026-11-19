import { useEffect, useRef, useState } from "react";
import { Download, Loader2, X } from "lucide-react";
import { downloadFile, fetchFileBlob } from "../api";

export interface PreviewFile {
  id: string;
  orig_name: string;
  mime: string;
}

type Kind = "image" | "pdf" | "audio" | "video" | "text" | "none";

function kindOf(file: PreviewFile): Kind {
  const m = (file.mime || "").toLowerCase();
  const n = file.orig_name.toLowerCase();
  const ext = (re: RegExp) => re.test(n);
  if (m.startsWith("image/") || ext(/\.(png|jpe?g|gif|webp|bmp|tiff?|ico|avif)$/)) return "image";
  if (m === "application/pdf") return "pdf";
  if (m.startsWith("audio/") || ext(/\.(mp3|wav|flac|aac|ogg|opus|m4a|aiff?)$/)) return "audio";
  if (m.startsWith("video/") || ext(/\.(mp4|webm|mkv|mov|avi|m4v)$/)) return "video";
  if (m.startsWith("text/") || ext(/\.(txt|md|markdown|csv|json|srt|vtt|html?|log|xml|ya?ml)$/)) return "text";
  return "none";
}

export default function FilePreview({ file, onClose }: { file: PreviewFile; onClose: () => void }) {
  const kind = kindOf(file);
  const dialog = useRef<HTMLDialogElement>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);

  useEffect(() => {
    if (kind === "none") return;
    const controller = new AbortController();
    const maxBytes = (kind === "text" ? 1 : kind === "video" || kind === "audio" ? 64 : 24) * 1024 * 1024;
    let obj: string | null = null;
    fetchFileBlob(file.id, { signal: controller.signal, maxBytes })
      .then(async (blob) => {
        if (kind === "text") {
          const excerpt = (await blob.text()).slice(0, 200_000);
          if (!controller.signal.aborted) setText(excerpt);
          return;
        }
        if (kind === "pdf" && !(await blob.slice(0, 1024).text()).includes("%PDF-")) {
          throw new Error("This PDF could not be verified for preview.");
        }
        if (!controller.signal.aborted) {
          obj = URL.createObjectURL(kind === "pdf" ? blob.slice(0, blob.size, "application/pdf") : blob);
          setUrl(obj);
        }
      })
      .catch((e) => { if (!controller.signal.aborted) setErr(e instanceof Error ? e.message : "Could not load preview."); });
    return () => { controller.abort(); if (obj) URL.revokeObjectURL(obj); };
  }, [file.id, kind]);

  const loading = kind !== "none" && !err && url === null && text === null;

  async function save() {
    setSaving(true);
    try {
      await downloadFile(file);
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Could not download the file.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <dialog ref={dialog} aria-label={`Preview ${file.orig_name}`}
      className="fixed m-auto w-[calc(100%-2rem)] max-w-4xl overflow-hidden rounded-2xl border border-line bg-surface text-fg shadow-[var(--shadow-pop)] backdrop:bg-black/60"
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="flex max-h-[88vh] flex-col overflow-hidden">
        <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
          <span className="min-w-0 flex-1 truncate font-medium text-fg">{file.orig_name}</span>
          <button type="button" disabled={saving} onClick={() => void save()} className="flex min-h-9 items-center gap-1 rounded-lg bg-surface-2 px-2.5 py-1 text-sm text-primary hover:bg-line disabled:opacity-50">
            <Download className="h-4 w-4" /> Download
          </button>
          <button type="button" aria-label="Close preview" onClick={onClose} className="grid size-9 shrink-0 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-fg">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-40 flex-1 overflow-auto bg-surface-2 p-4">
          {err && <p className="text-sm text-danger" role="alert">{err}</p>}
          {kind === "none" && <p className="text-sm text-muted">Download this file to open it.</p>}
          {loading && <div className="flex items-center gap-2 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin" /> loading…</div>}
          {kind === "image" && url && <img src={url} alt={file.orig_name} className="mx-auto max-h-[70vh] max-w-full rounded-lg" />}
          {kind === "pdf" && url && <iframe src={url} title={file.orig_name} referrerPolicy="no-referrer" className="h-[72vh] w-full rounded-lg bg-white" />}
          {kind === "audio" && url && <audio src={url} controls className="mt-6 w-full" />}
          {kind === "video" && url && <video src={url} controls className="mx-auto max-h-[70vh] max-w-full rounded-lg" />}
          {kind === "text" && text !== null && <pre className="whitespace-pre-wrap break-words text-sm leading-relaxed text-fg">{text}</pre>}
        </div>
      </div>
    </dialog>
  );
}
