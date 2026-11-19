import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, FileText, GripVertical, RotateCcw, X } from "lucide-react";
import type { PDFDocumentLoadingTask, PDFWorker, RenderTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

const MAX_PREVIEW_BYTES = 32 * 1024 * 1024;
const MAX_VISUAL_PAGES = 100;
const MAX_THUMBNAILS = 24;
const PREVIEW_TIMEOUT_MS = 15_000;
const RANGE = /^(\d+)?-(\d+)?$/;

function parsePages(spec: string, total: number, whenEmpty: number[]): number[] | null {
  if (!spec.trim()) return whenEmpty;
  const pages = new Set<number>();
  for (const token of spec.replaceAll(" ", "").split(",").filter(Boolean)) {
    const range = token.match(RANGE);
    if (!range && !/^\d+$/.test(token)) return null;
    const start = range ? Number(range[1] ?? 1) : Number(token);
    const end = range ? Number(range[2] ?? total) : start;
    if (start < 1 || end > total || start > end) return null;
    for (let page = start; page <= end; page += 1) pages.add(page);
  }
  return [...pages];
}

type Preview =
  | { file: File; state: "ready"; total: number; thumbnails: Record<number, string> }
  | { file: File; state: "unavailable"; reason: string };

export default function PdfOrganizer({
  file, pageOrder, removePages, disabled, onChange,
}: {
  file: File;
  pageOrder: string;
  removePages: string;
  disabled: boolean;
  onChange: (pageOrder: string, removePages: string) => void;
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [dragging, setDragging] = useState<number | null>(null);
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    let active = true;
    let countedPages = false;
    let loading: PDFDocumentLoadingTask | undefined;
    let rendering: RenderTask | undefined;
    let thread: Worker | undefined;
    let worker: PDFWorker | undefined;
    const unavailable = (reason: string) => {
      if (active) setPreview({ file, state: "unavailable", reason });
    };
    const stop = () => {
      active = false;
      rendering?.cancel();
      worker?.destroy();
      thread?.terminate();
    };
    const timeout = window.setTimeout(() => {
      if (!countedPages) unavailable("Preview took too long. Enter page ranges below to edit this PDF.");
      stop();
    }, PREVIEW_TIMEOUT_MS);

    async function load() {
      if (file.size > MAX_PREVIEW_BYTES) {
        unavailable("Visual preview supports files up to 32 MiB. Enter page ranges below for this PDF.");
        window.clearTimeout(timeout);
        return;
      }

      try {
        const pdfjs = await import("pdfjs-dist");
        if (!active) return;
        const data = new Uint8Array(await file.arrayBuffer());
        if (!active) return;
        thread = new Worker(workerUrl, { type: "module" });
        worker = pdfjs.PDFWorker.create({ port: thread, verbosity: pdfjs.VerbosityLevel.ERRORS });
        loading = pdfjs.getDocument({
          data,
          worker,
          enableXfa: false,
          maxImageSize: 8_000_000,
          canvasMaxAreaInBytes: MAX_PREVIEW_BYTES,
          useWasm: false,
          verbosity: pdfjs.VerbosityLevel.ERRORS,
        });
        const document = await loading.promise;
        if (!active) return;
        countedPages = true;
        const total = document.numPages;
        if (total > MAX_VISUAL_PAGES) {
          unavailable(`This PDF has ${total} pages. Enter page ranges below to edit it.`);
          return;
        }
        setPreview({ file, state: "ready", total, thumbnails: {} });
        for (let number = 1; active && number <= Math.min(total, MAX_THUMBNAILS); number += 1) {
          try {
            const page = await document.getPage(number);
            if (!active) break;
            const original = page.getViewport({ scale: 1 });
            const scale = Math.min(200 / original.width, 168 / original.height, 1.5);
            if (!Number.isFinite(scale) || scale <= 0) continue;
            const viewport = page.getViewport({ scale });
            const canvas = window.document.createElement("canvas");
            canvas.width = Math.max(1, Math.ceil(viewport.width));
            canvas.height = Math.max(1, Math.ceil(viewport.height));
            rendering = page.render({ canvas, viewport, annotationMode: pdfjs.AnnotationMode.DISABLE });
            await rendering.promise;
            const image = canvas.toDataURL("image/jpeg", 0.73);
            if (active) setPreview((current) =>
              current?.file === file && current.state === "ready"
                ? { ...current, thumbnails: { ...current.thumbnails, [number]: image } }
                : current,
            );
            page.cleanup();
          } catch {
            // Retain numbered controls for pages that are too complex to preview.
          } finally {
            rendering = undefined;
          }
        }
      } catch {
        unavailable("The browser could not preview this PDF. Enter page ranges below.");
      } finally {
        if (active) await loading?.destroy().catch(() => undefined);
        window.clearTimeout(timeout);
        stop();
      }
    }

    void load();
    return () => {
      window.clearTimeout(timeout);
      stop();
    };
  }, [file]);

  const current = preview?.file === file ? preview : null;
  if (!current) return <p role="status" className="text-sm text-muted">Reading PDF pages…</p>;
  if (current.state === "unavailable") return <p role="status" className="text-sm text-muted">{current.reason}</p>;

  const all = Array.from({ length: current.total }, (_, index) => index + 1);
  const order = parsePages(pageOrder, current.total, all);
  const removed = parsePages(removePages, current.total, []);
  if (!order || !removed) {
    return <p role="status" className="text-sm text-muted">Correct the page ranges below to use the visual editor.</p>;
  }
  const selected = order.filter((page) => !removed.includes(page));
  const hidden = all.filter((page) => !selected.includes(page));
  const changed = hidden.length > 0 || selected.some((page, index) => page !== all[index]);

  function apply(selection: number[], message: string) {
    const original = selection.length === all.length && selection.every((page, index) => page === all[index]);
    onChange(original ? "" : selection.join(","), "");
    setAnnouncement(message);
  }

  function move(from: number, to: number) {
    if (disabled || from < 0 || to < 0 || from === to || to >= selected.length) return;
    const selection = [...selected];
    const page = selection[from];
    selection.splice(from, 1);
    selection.splice(to, 0, page);
    apply(selection, `Moved page ${page} to position ${to + 1}.`);
  }

  const control = "grid size-8 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-35";

  return (
    <div className="rounded-2xl border border-line bg-surface p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-fg">Page order</h2>
          <p className="mt-1 text-sm text-muted">
            {selected.length} of {current.total} pages kept. Drag pages or use the arrow buttons.
          </p>
        </div>
        <button
          type="button" disabled={disabled || !changed}
          onClick={() => apply(all, "Restored the original page order.")}
          className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-line px-2.5 text-sm text-muted hover:text-fg disabled:opacity-35"
        >
          <RotateCcw className="size-4" aria-hidden="true" /> Reset order
        </button>
      </div>
      <p className="sr-only" role="status">{announcement}</p>
      <ol aria-label="PDF pages in output order" className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
        {selected.map((page, index) => (
          <li
            key={page}
            draggable={!disabled}
            onDragStart={(event) => {
              event.dataTransfer.setData("application/x-selfx-pdf-page", String(page));
              event.dataTransfer.effectAllowed = "move";
              setDragging(page);
            }}
            onDragOver={(event) => {
              if (dragging !== null && !disabled) {
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
              }
            }}
            onDrop={(event) => {
              if (dragging === null || disabled) return;
              event.preventDefault();
              move(selected.indexOf(dragging), index);
              setDragging(null);
            }}
            onDragEnd={() => setDragging(null)}
            className={`min-w-0 overflow-hidden rounded-xl border border-line ${dragging === page ? "opacity-50" : ""}`}
          >
            <div className="grid h-24 place-items-center bg-surface-2 p-2 sm:h-28">
              {current.thumbnails[page]
                ? <img alt="" draggable={false} src={current.thumbnails[page]} className="h-full max-h-full w-full object-contain" />
                : <FileText className="size-7 text-faint" aria-hidden="true" />}
            </div>
            <div className="flex items-center gap-1 px-2 py-1 text-xs font-semibold text-fg">
              <GripVertical className="size-3.5 text-faint" aria-hidden="true" />
              Page {page}
            </div>
            <div className="flex items-center justify-between border-t border-line px-0.5">
              <button type="button" disabled={disabled || index === 0} onClick={() => move(index, index - 1)} aria-label={`Move page ${page} earlier`} className={control}>
                <ArrowLeft className="size-4" aria-hidden="true" />
              </button>
              <button type="button" disabled={disabled || index === selected.length - 1} onClick={() => move(index, index + 1)} aria-label={`Move page ${page} later`} className={control}>
                <ArrowRight className="size-4" aria-hidden="true" />
              </button>
              <button
                type="button" disabled={disabled || selected.length === 1}
                onClick={() => apply(selected.filter((number) => number !== page), `Removed page ${page}.`)}
                aria-label={`Remove page ${page}`} className={control}
              >
                <X className="size-4" aria-hidden="true" />
              </button>
            </div>
          </li>
        ))}
      </ol>
      {hidden.length > 0 && (
        <div className="mt-4">
          <h3 className="text-sm font-medium text-fg">Restore removed pages</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {hidden.map((page) => (
              <button
                key={page} type="button" disabled={disabled}
                onClick={() => apply([...selected, page], `Restored page ${page} at the end.`)}
                className="rounded-lg border border-line px-2.5 py-1.5 text-xs text-muted hover:text-fg disabled:opacity-35"
              >
                Restore page {page}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
