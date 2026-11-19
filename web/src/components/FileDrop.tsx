import { useRef, useState, type DragEvent } from "react";
import { File as FileIcon, Upload, X } from "lucide-react";
import { formatBytes } from "../format";
import { acceptsFilename } from "../toolDiscovery";

interface Props {
  accepts: string[]; // allowed extensions like [".pdf"]; empty = anything
  formatHint?: string;
  multiple: boolean;
  files: File[];
  onChange: (files: File[]) => void;
  disabled?: boolean;
}

export default function FileDrop({
  accepts,
  formatHint,
  multiple,
  files,
  onChange,
  disabled = false,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [rejected, setRejected] = useState<string[]>([]);

  const addFiles = (incoming: FileList | File[]) => {
    const accepted: File[] = [];
    const bad: string[] = [];
    for (const f of Array.from(incoming)) {
      if (acceptsFilename(f.name, accepts)) accepted.push(f);
      else bad.push(f.name);
    }
    setRejected(bad);
    if (accepted.length === 0) return;
    if (multiple) {
      // Skip duplicates by name+size.
      const existing = new Set(files.map((f) => `${f.name}:${f.size}`));
      const fresh = accepted.filter((f) => !existing.has(`${f.name}:${f.size}`));
      onChange([...files, ...fresh]);
    } else {
      onChange([accepted[0]]);
    }
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (disabled) return;
    if (e.dataTransfer.files.length > 0) addFiles(e.dataTransfer.files);
  };

  const removeAt = (idx: number) => {
    onChange(files.filter((_, i) => i !== idx));
  };

  return (
    <div>
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(e) => {
          if (!disabled && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={[
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed p-8 text-center transition-colors",
          dragOver
            ? "border-primary bg-primary-soft"
            : "border-line bg-surface-2 hover:border-primary",
          disabled ? "pointer-events-none opacity-50" : "",
        ].join(" ")}
      >
        <Upload className="h-6 w-6 text-muted" />
        <p className="text-sm text-fg">
          Drop {multiple ? "files" : "a file"} here or{" "}
          <span className="text-primary">browse</span>
        </p>
        <p className="text-xs text-muted">
          {formatHint ?? (accepts.length > 0 ? `Accepted: ${accepts.join(", ")}` : "Any file type")}
        </p>
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          multiple={multiple}
          disabled={disabled}
          accept={accepts.length > 0 ? accepts.join(",") : undefined}
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {rejected.length > 0 && (
        <p className="mt-2 text-xs text-warn">
          Skipped (type not accepted): {rejected.join(", ")}
        </p>
      )}

      {files.length > 0 && (
        <ul className="mt-3 divide-y divide-line rounded-xl border border-line bg-surface-2">
          {files.map((f, i) => (
            <li
              key={`${f.name}:${f.size}:${i}`}
              className="flex items-center gap-2 px-3 py-2 text-sm"
            >
              <FileIcon className="h-4 w-4 shrink-0 text-faint" />
              <span className="min-w-0 flex-1 truncate text-fg">
                {f.name}
              </span>
              <span className="shrink-0 text-xs text-muted">
                {formatBytes(f.size)}
              </span>
              <button
                type="button"
                onClick={() => removeAt(i)}
                disabled={disabled}
                className="shrink-0 rounded-full p-1 text-muted transition-colors hover:bg-line hover:text-danger"
                aria-label={`Remove ${f.name}`}
              >
                <X className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
