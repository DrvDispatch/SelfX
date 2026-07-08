import { useEffect, useState } from "react";
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
  if (m === "application/pdf" || ext(/\.pdf$/)) return "pdf";
  if (m.startsWith("audio/") || ext(/\.(mp3|wav|flac|aac|ogg|opus|m4a|aiff?)$/)) return "audio";
  if (m.startsWith("video/") || ext(/\.(mp4|webm|mkv|mov|avi|m4v)$/)) return "video";
  if (m.startsWith("text/") || ext(/\.(txt|md|markdown|csv|json|srt|vtt|html?|log|xml|ya?ml)$/)) return "text";
  return "none";
}

export default function FilePreview({ file, onClose }: { file: PreviewFile; onClose: () => void }) {
  const kind = kindOf(file);
  const [url, setUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (kind === "none") return;
    let obj: string | null = null;
    let cancelled = false;
    fetchFileBlob(file.id)
      .then(async (blob) => {
        if (cancelled) return;
        if (kind === "text") setText((await blob.text()).slice(0, 200_000));
        else { obj = URL.createObjectURL(blob); setUrl(obj); }
      })
      .catch((e) => !cancelled && setErr(e instanceof Error ? e.message : "preview failed"));
    return () => { cancelled = true; if (obj) URL.revokeObjectURL(obj); };
  }, [file.id, kind]);

  const loading = kind !== "none" && !err && url === null && text === null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-[var(--shadow-pop)]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
          <span className="min-w-0 flex-1 truncate font-medium text-fg">{file.orig_name}</span>
          <button onClick={() => void downloadFile(file)} className="flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-1 text-sm text-primary hover:bg-line">
            <Download className="h-4 w-4" /> Download
          </button>
          <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-fg">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-40 flex-1 overflow-auto bg-surface-2 p-4">
          {err && <p className="text-sm text-danger">{err}</p>}
          {kind === "none" && <p className="text-sm text-muted">No inline preview for this file type — use Download.</p>}
          {loading && <div className="flex items-center gap-2 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin" /> loading…</div>}
          {kind === "image" && url && <img src={url} alt={file.orig_name} className="mx-auto max-h-[70vh] max-w-full rounded-lg" />}
          {kind === "pdf" && url && <iframe src={url} title={file.orig_name} className="h-[72vh] w-full rounded-lg bg-white" />}
          {kind === "audio" && url && <audio src={url} controls className="mt-6 w-full" />}
          {kind === "video" && url && <video src={url} controls className="mx-auto max-h-[70vh] max-w-full rounded-lg" />}
          {kind === "text" && text !== null && <pre className="whitespace-pre-wrap break-words text-sm leading-relaxed text-fg">{text}</pre>}
        </div>
      </div>
    </div>
  );
}
