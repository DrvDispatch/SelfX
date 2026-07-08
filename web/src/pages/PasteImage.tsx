import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  AppWindow,
  ChevronDown,
  Clipboard,
  ClipboardPaste,
  Download,
  Eraser,
  FileText,
  Image as ImageIcon,
  Maximize2,
  MessageSquareText,
  Minimize2,
  RefreshCw,
  ScanText,
  ShieldOff,
  Upload,
  X,
  type LucideIcon,
} from "lucide-react";
import { listTools } from "../api";
import {
  MAX_IMAGE_BYTES,
  canReadClipboard,
  readClipboardImage,
  screenshotName,
  withImageExt,
} from "../clipboard";
import { useToast } from "../components/Toast";
import { formatBytes } from "../format";
import type { ToolInfo } from "../types";

interface QuickAction {
  slug: string;
  label: string;
  icon: LucideIcon;
  primary?: boolean;
}

// Ordered by intent for a pasted SCREENSHOT: lift text first, then shrink/convert,
// then background removal; niche/format actions live under "More tools".
const ACTIONS: QuickAction[] = [
  { slug: "image-to-text", label: "Extract text", icon: ScanText, primary: true },
  { slug: "image-optimize", label: "Compress", icon: Minimize2, primary: true },
  { slug: "image-convert", label: "Convert", icon: RefreshCw, primary: true },
  { slug: "image-remove-bg", label: "Remove background", icon: Eraser, primary: true },
  { slug: "image-upscale", label: "Upscale", icon: Maximize2 },
  { slug: "images-to-pdf", label: "Save as PDF", icon: FileText },
  { slug: "image-caption", label: "Describe (alt text)", icon: MessageSquareText },
  { slug: "image-to-ico", label: "Make icon", icon: AppWindow },
  { slug: "metadata-remove", label: "Strip metadata", icon: ShieldOff },
];

export default function PasteImage() {
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const [img, setImg] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [url, setUrl] = useState<string | null>(null);
  const [tools, setTools] = useState<Record<string, ToolInfo>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [showMore, setShowMore] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listTools()
      .then((all) => setTools(Object.fromEntries(all.map((t) => [t.slug, t]))))
      .catch(() => undefined);
  }, []);

  // Accept an image handed off via router state (from the global paste listener),
  // re-reading whenever a fresh paste navigates here (location.key changes).
  useEffect(() => {
    const pasted = (location.state as { pastedImage?: File } | null)?.pastedImage;
    if (pasted instanceof File) accept(pasted);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key]);

  // Manage the preview object URL like FilePreview: create on change, revoke on cleanup.
  useEffect(() => {
    if (!img) {
      setUrl(null);
      return;
    }
    const obj = URL.createObjectURL(img);
    setUrl(obj);
    return () => URL.revokeObjectURL(obj);
  }, [img]);

  const accept = (file: File) => {
    setNotice(null);
    if (!file.type.startsWith("image/")) {
      setNotice("That doesn't look like an image.");
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setNotice(`That image is ${formatBytes(file.size)} — larger than the ${formatBytes(MAX_IMAGE_BYTES)} limit.`);
      return;
    }
    setImg(file);
    setName(file.name || screenshotName(file.type));
  };

  const onPasteButton = async () => {
    setNotice(null);
    try {
      const file = await readClipboardImage();
      if (file) accept(file);
      else setNotice("No image found on the clipboard.");
    } catch {
      setNotice("Couldn't read the clipboard — press Ctrl/⌘+V instead, or browse for a file.");
    }
  };

  const currentFile = useMemo(() => {
    if (!img) return null;
    const finalName = withImageExt(name.trim() || screenshotName(img.type), img.type);
    return new File([img], finalName, { type: img.type, lastModified: img.lastModified });
  }, [img, name]);

  const download = () => {
    if (!currentFile || !url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = currentFile.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast.success(`Saved ${currentFile.name}`);
  };

  const runTool = (slug: string) => {
    if (!currentFile) return;
    navigate(`/tool/${slug}`, { state: { presetFiles: [currentFile] } });
  };

  const reset = () => {
    setImg(null);
    setName("");
    setNotice(null);
    setShowMore(false);
  };

  // ---- empty state ----
  if (!img) {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <div className="rounded-3xl border border-line bg-surface p-8 text-center sm:p-12">
          <span className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-primary-soft">
            <Clipboard className="h-7 w-7 text-primary" />
          </span>
          <h1 className="text-2xl font-bold text-fg">Paste a screenshot</h1>
          <p className="mx-auto mt-2 max-w-md text-muted">
            Press <kbd className="rounded bg-surface-2 px-1.5 py-0.5 text-xs text-fg">⌘V</kbd>{" "}
            (<kbd className="rounded bg-surface-2 px-1.5 py-0.5 text-xs text-fg">Ctrl+V</kbd> on Windows)
            anywhere to drop your latest screenshot here.
          </p>
          <p className="mx-auto mt-1.5 max-w-md text-sm text-muted">
            We&apos;ll give it a clean filename you can download in one click — then run OCR, compress it,
            convert it, and more.
          </p>

          <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
            {canReadClipboard() && (
              <button
                onClick={() => void onPasteButton()}
                className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-fg transition-opacity hover:opacity-90"
              >
                <ClipboardPaste className="h-4 w-4" /> Paste from clipboard
              </button>
            )}
            <button
              onClick={() => inputRef.current?.click()}
              className="inline-flex items-center gap-2 rounded-xl bg-surface-2 px-4 py-2 text-sm font-medium text-fg transition-colors hover:bg-line"
            >
              <Upload className="h-4 w-4" /> Browse for an image
            </button>
            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                if (e.target.files?.[0]) accept(e.target.files[0]);
                e.target.value = "";
              }}
            />
          </div>

          {notice && <p className="mt-4 text-sm text-warn">{notice}</p>}
          <p className="mt-6 text-xs text-faint">Nothing leaves your machine until you run a tool.</p>
        </div>
      </div>
    );
  }

  // ---- loaded state ----
  const primary = ACTIONS.filter((a) => a.primary);
  const more = ACTIONS.filter((a) => !a.primary);

  const actionButton = (a: QuickAction) => {
    const t = tools[a.slug];
    const known = t !== undefined;
    const available = known && t.available;
    const Icon = a.icon;
    return (
      <button
        key={a.slug}
        onClick={() => runTool(a.slug)}
        disabled={known && !available}
        title={!known ? "" : !available ? `Unavailable${t.unavailable_reason ? `: ${t.unavailable_reason}` : ""}` : t.description}
        className="flex items-center gap-3 rounded-xl border border-line bg-surface-2 p-3 text-left transition-colors hover:border-primary disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-primary-soft">
          <Icon className="h-4.5 w-4.5 text-primary" />
        </span>
        <span className="min-w-0">
          <span className="block truncate font-medium text-fg">{a.label}</span>
          {known && <span className="block truncate text-xs text-muted">{t.name}</span>}
        </span>
      </button>
    );
  };

  return (
    <div className="mx-auto max-w-2xl p-6">
      <div className="mb-4 flex items-center gap-2">
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-primary-soft">
          <ImageIcon className="h-5 w-5 text-primary" />
        </span>
        <h1 className="mr-auto font-bold text-fg">Your image</h1>
        <button
          onClick={reset}
          className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-3 py-1.5 text-sm text-muted transition-colors hover:text-fg"
        >
          <X className="h-4 w-4" /> Paste another
        </button>
      </div>

      <div className="overflow-hidden rounded-2xl border border-line bg-surface-2">
        {url && (
          <img
            src={url}
            alt={name}
            className="mx-auto max-h-[56vh] w-auto max-w-full object-contain"
          />
        )}
      </div>

      <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          spellCheck={false}
          className="min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 py-2.5 text-sm text-fg outline-none focus:border-primary"
        />
        <span className="shrink-0 text-xs text-muted">{formatBytes(img.size)}</span>
        <button
          onClick={download}
          className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-fg transition-opacity hover:opacity-90"
        >
          <Download className="h-4 w-4" /> Download
        </button>
      </div>

      {notice && <p className="mt-3 text-sm text-warn">{notice}</p>}

      <div className="mt-6">
        <h2 className="mb-2 text-sm font-medium text-fg">What next?</h2>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">{primary.map(actionButton)}</div>

        <button
          onClick={() => setShowMore((s) => !s)}
          className="mt-3 inline-flex items-center gap-1 text-sm text-muted transition-colors hover:text-fg"
        >
          <ChevronDown className={`h-4 w-4 transition-transform ${showMore ? "rotate-180" : ""}`} />
          {showMore ? "Fewer tools" : "More tools"}
        </button>
        {showMore && (
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">{more.map(actionButton)}</div>
        )}
      </div>
    </div>
  );
}
