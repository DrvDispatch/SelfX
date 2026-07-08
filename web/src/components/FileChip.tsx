import { useEffect, useState } from "react";
import {
  Archive,
  CheckCircle2,
  File as FileIcon,
  FileText,
  Image as ImageIcon,
  Loader2,
  Music,
  Video,
  X,
  XCircle,
} from "lucide-react";
import { formatBytes } from "../format";

export type UploadStatus = "pending" | "uploading" | "done" | "error";

export interface UploadItem {
  key: string;
  file: File;
  progress: number; // 0..1
  status: UploadStatus;
  error?: string;
  id?: string; // server file id once uploaded
}

function iconFor(name: string): typeof FileIcon {
  const n = name.toLowerCase();
  if (/\.(png|jpe?g|gif|webp|bmp|tiff?|svg|avif|heic|ico)$/.test(n)) return ImageIcon;
  if (/\.(mp4|mov|mkv|webm|avi|m4v|flv|wmv|mpe?g)$/.test(n)) return Video;
  if (/\.(mp3|wav|flac|aac|ogg|opus|m4a|wma|aiff?)$/.test(n)) return Music;
  if (/\.(zip|7z|tar|gz|tgz|rar|bz2|xz)$/.test(n)) return Archive;
  if (/\.(pdf|docx?|txt|md|rtf|odt|epub|html?|csv|json|srt|vtt)$/.test(n)) return FileText;
  return FileIcon;
}

/** A single attached / uploading file, with a thumbnail for images and live state. */
export default function FileChip({
  item,
  onRemove,
  disabled = false,
}: {
  item: UploadItem;
  onRemove?: () => void;
  disabled?: boolean;
}) {
  const [thumb, setThumb] = useState<string | null>(null);

  useEffect(() => {
    if (!item.file.type.startsWith("image/")) return;
    const url = URL.createObjectURL(item.file);
    setThumb(url);
    return () => URL.revokeObjectURL(url);
  }, [item.file]);

  const Icon = iconFor(item.file.name);
  const pct = Math.round(item.progress * 100);

  return (
    <div className="group relative flex items-center gap-3 overflow-hidden rounded-xl border border-line bg-surface-2 px-3 py-2">
      <span className="grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded-lg bg-surface">
        {thumb ? (
          <img src={thumb} alt="" className="h-full w-full object-cover" />
        ) : (
          <Icon className="h-4.5 w-4.5 text-muted" />
        )}
      </span>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-fg">{item.file.name}</p>
        <p className="flex items-center gap-1.5 text-xs text-muted">
          {item.status === "uploading" && (
            <span className="flex items-center gap-1 text-primary">
              <Loader2 className="h-3 w-3 animate-spin" /> Uploading {pct}%
            </span>
          )}
          {item.status === "pending" && <span className="text-faint">Ready to send</span>}
          {item.status === "done" && (
            <span className="flex items-center gap-1 text-ok">
              <CheckCircle2 className="h-3 w-3" /> Uploaded
            </span>
          )}
          {item.status === "error" && (
            <span className="flex items-center gap-1 text-danger">
              <XCircle className="h-3 w-3" /> {item.error || "Failed"}
            </span>
          )}
          <span className="text-faint">· {formatBytes(item.file.size)}</span>
        </p>
      </div>

      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          disabled={disabled}
          aria-label={`Remove ${item.file.name}`}
          className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-faint transition-colors hover:bg-line hover:text-danger disabled:opacity-40"
        >
          <X className="h-4 w-4" />
        </button>
      )}

      {item.status === "uploading" && (
        <span className="absolute inset-x-0 bottom-0 h-0.5 bg-line">
          <span
            className="block h-full bg-primary transition-[width] duration-150"
            style={{ width: `${pct}%` }}
          />
        </span>
      )}
    </div>
  );
}
