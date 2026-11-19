import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, AudioLines, ChevronLeft, ChevronRight, Copy, Download, FileText, Search } from "lucide-react";
import { ApiError, createJob, fetchFileBlob, getWorkflowRun, uploadFile } from "../api";
import { useToast } from "../components/Toast";
import {
  editedSegment, exportTranscript, parseTranscript, timestamp, TRANSCRIPT_MAX_BYTES,
  type Transcript, type TranscriptFormat, type TranscriptSegment,
} from "../transcript";
import type { FileInfo } from "../types";

const PAGE_SIZE = 25;
const MEDIA_LIMIT = 64 * 1024 * 1024;
const FORMATS: TranscriptFormat[] = ["txt", "srt", "vtt", "json"];
const field = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-fg";
const button = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line px-3 text-sm font-medium text-fg hover:bg-surface-2 disabled:opacity-50";

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function SegmentEditor({ segment, index, onSave }: {
  segment: TranscriptSegment;
  index: number;
  onSave: (text: string, start: string, end: string) => void;
}) {
  const [text, setText] = useState(segment.text);
  const [start, setStart] = useState(String(segment.start));
  const [end, setEnd] = useState(String(segment.end));
  const [error, setError] = useState("");
  const changed = text !== segment.text || start !== String(segment.start) || end !== String(segment.end);

  function save(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      onSave(text, start, end);
    } catch (failure) {
      setError(errorMessage(failure, "Could not apply the change."));
    }
  }

  return (
    <form className="space-y-4" onSubmit={save}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold text-fg">Segment {index + 1}</h2>
        {segment.speaker && <span className="text-sm text-muted">{segment.speaker}</span>}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <label className="space-y-1.5 text-sm font-medium text-fg">
          <span className="block">Start (seconds)</span>
          <input className={field} inputMode="decimal" value={start} onChange={(event) => setStart(event.target.value)} required />
        </label>
        <label className="space-y-1.5 text-sm font-medium text-fg">
          <span className="block">End (seconds)</span>
          <input className={field} inputMode="decimal" value={end} onChange={(event) => setEnd(event.target.value)} required />
        </label>
      </div>
      <label className="block space-y-1.5 text-sm font-medium text-fg">
        <span className="block">Transcript text</span>
        <textarea value={text} className={`${field} min-h-36 resize-y leading-relaxed`} maxLength={8000}
          onChange={(event) => setText(event.target.value)} required />
      </label>
      {error && <p className="text-sm text-danger" role="alert">{error}</p>}
      <button type="submit" disabled={!changed} className="min-h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-fg disabled:opacity-50">
        Apply changes
      </button>
    </form>
  );
}

export default function TranscriptEditorRoute() {
  const { id, fileId } = useParams<{ id: string; fileId: string }>();
  return id && fileId ? <TranscriptEditor key={`${id}:${fileId}`} id={id} fileId={fileId} /> : null;
}

function TranscriptEditor({ id, fileId }: { id: string; fileId: string }) {
  const toast = useToast();
  const [document, setDocument] = useState<Transcript | null>(null);
  const [title, setTitle] = useState("Transcript");
  const [source, setSource] = useState<FileInfo | null>(null);
  const [loadError, setLoadError] = useState("");
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState(0);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [format, setFormat] = useState<TranscriptFormat>("srt");
  const [pdfPending, setPdfPending] = useState(false);
  const exporting = useRef(false);
  const [pdfJob, setPdfJob] = useState<string | null>(null);
  const [mediaLoading, setMediaLoading] = useState(false);
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const mediaRequest = useRef<AbortController | null>(null);
  const player = useRef<HTMLMediaElement | null>(null);
  const seek = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoadError("");
    void (async () => {
      try {
        const run = await getWorkflowRun(id, controller.signal);
        const file = run.output_files.find((result) => result.id === fileId);
        if (!file) throw new Error("That transcript is no longer available for this workflow.");
        if (file.size > TRANSCRIPT_MAX_BYTES) throw new Error("This transcript is over the 12 MiB editor limit.");
        const blob = await fetchFileBlob(file.id, { signal: controller.signal, maxBytes: TRANSCRIPT_MAX_BYTES });
        const transcript = parseTranscript(await blob.text());
        if (controller.signal.aborted) return;
        setDocument(transcript);
        if (run.tool === "workflow:transcript-pdf") setSource(run.input_files[0] ?? null);
        if (typeof run.params.title === "string") setTitle(run.params.title);
      } catch (error) {
        if (!controller.signal.aborted) {
          setLoadError(error instanceof ApiError ? error.detail : error instanceof SyntaxError
            ? "The file isn't valid transcript JSON." : errorMessage(error, "Could not open the transcript."));
        }
      }
    })();
    return () => controller.abort();
  }, [id, fileId, revision]);

  useEffect(() => () => mediaRequest.current?.abort(), []);
  useEffect(() => () => { if (mediaUrl) URL.revokeObjectURL(mediaUrl); }, [mediaUrl]);

  const rows = useMemo(() => {
    const filter = query.trim().toLowerCase();
    return document?.segments.map((segment, index) => ({ segment, index }))
      .filter(({ segment }) => !filter || segment.text.toLowerCase().includes(filter)) ?? [];
  }, [document, query]);
  const lastPage = Math.max(0, Math.ceil(rows.length / PAGE_SIZE) - 1);
  const currentPage = Math.min(lastPage, page);
  const current = document?.segments[selected];
  const preview = source && source.size <= MEDIA_LIMIT && /^(audio|video)\//.test(source.mime);

  async function loadRecording() {
    if (!preview || mediaRequest.current) return;
    const controller = new AbortController();
    mediaRequest.current = controller;
    setMediaLoading(true);
    try {
      const blob = await fetchFileBlob(source.id, { signal: controller.signal, maxBytes: MEDIA_LIMIT });
      if (!controller.signal.aborted) setMediaUrl(URL.createObjectURL(blob));
    } catch (error) {
      if (!controller.signal.aborted) toast.error(errorMessage(error, "Could not load the recording."));
    } finally {
      if (!controller.signal.aborted) setMediaLoading(false);
      mediaRequest.current = null;
    }
  }

  function selectSegment(index: number, start: number) {
    setSelected(index);
    seek.current = start;
    if (player.current?.readyState) player.current.currentTime = start;
  }

  function apply(text: string, start: string, end: string) {
    if (!document) return;
    const segment = editedSegment(document.segments, selected, text, start, end);
    setDocument({
      ...document,
      duration: Math.max(document.duration, segment.end),
      segments: document.segments.map((item, index) => index === selected ? segment : item),
    });
    toast.success("Transcript updated");
  }

  function download() {
    if (!document) return;
    const file = new Blob([exportTranscript(document, format)], { type: "application/octet-stream" });
    const url = URL.createObjectURL(file);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = `transcript-edited.${format}`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast.success("Download started");
  }

  async function copy() {
    if (!document) return;
    try {
      await navigator.clipboard.writeText(exportTranscript(document, "txt"));
      toast.success("Transcript copied");
    } catch {
      toast.error("Clipboard unavailable. You can download a TXT copy instead.");
    }
  }

  async function exportPdf() {
    if (!document || exporting.current) return;
    exporting.current = true;
    setPdfPending(true);
    setPdfJob(null);
    try {
      const file = new File([exportTranscript(document, "json")], "transcript-edited.json", { type: "application/json" });
      if (file.size > TRANSCRIPT_MAX_BYTES) throw new Error("The edited transcript is over the 12 MiB PDF export limit.");
      const stored = await uploadFile(file);
      const job = await createJob("transcript-export", [stored.id], { title: title.slice(0, 160) });
      setPdfJob(job.id);
      toast.success("PDF export queued");
    } catch (error) {
      toast.error(errorMessage(error, "Could not queue the PDF export."));
    } finally {
      exporting.current = false;
      setPdfPending(false);
    }
  }

  function attachPlayer(element: HTMLMediaElement | null) {
    player.current = element;
  }

  function positionPlayer() {
    if (player.current) player.current.currentTime = seek.current;
  }

  return (
    <div className="mx-auto max-w-6xl">
      <Link to={`/runs/${id}`} className="mb-5 inline-flex min-h-9 items-center gap-2 text-sm font-medium text-primary">
        <ArrowLeft aria-hidden className="size-4" /> Back to workflow
      </Link>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-fg">Edit transcript</h1>
          {document && <p className="mt-1 text-sm text-muted">{document.segments.length} segments · {timestamp(document.duration).split(".")[0]}</p>}
        </div>
        {document && (
          <div className="flex flex-wrap gap-2">
            <button type="button" className={button} onClick={() => void copy()}><Copy aria-hidden className="size-4" /> Copy text</button>
            <label className="sr-only" htmlFor="transcript-format">Download format</label>
            <select id="transcript-format" className={`${field} !w-auto`} value={format}
              onChange={(event) => setFormat(event.target.value as TranscriptFormat)}>
              {FORMATS.map((item) => <option key={item} value={item}>{item.toUpperCase()}</option>)}
            </select>
            <button type="button" className={button} onClick={download}>
              <Download aria-hidden className="size-4" /> Download
            </button>
            <button type="button" className={button} disabled={pdfPending} onClick={() => void exportPdf()}>
              <FileText aria-hidden className="size-4" /> {pdfPending ? "Queueing PDF…" : "Export PDF & SRT"}
            </button>
          </div>
        )}
      </div>
      {pdfJob && <p role="status" className="mb-4 rounded-lg bg-primary-soft p-3 text-sm text-primary">
        PDF export queued. <Link className="font-medium underline" to={`/jobs?highlight=${pdfJob}`}>Open Activity</Link>
      </p>}
      {loadError ? (
        <div className="rounded-xl border border-line bg-surface p-5">
          <p className="mb-3 text-sm text-danger" role="alert">{loadError}</p>
          <button type="button" className={button} onClick={() => setRevision((value) => value + 1)}>Try again</button>
        </div>
      ) : !document ? <p className="text-sm text-muted" role="status">Opening transcript…</p> : (
        <div className="grid items-start gap-5 lg:grid-cols-[1fr_1fr]">
          <section aria-label="Transcript segments" className="min-w-0 rounded-xl border border-line bg-surface p-4 sm:p-5">
            <label className="relative block">
              <span className="sr-only">Search transcript</span>
              <Search aria-hidden className="pointer-events-none absolute left-3 top-3 size-4 text-muted" />
              <input type="search" className={`${field} pl-9`} placeholder="Find a word or phrase"
                value={query} onChange={(event) => { setQuery(event.target.value); setPage(0); }} />
            </label>
            <ul className="mt-3 max-h-[60vh] divide-y divide-line overflow-auto">
              {rows.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE).map(({ segment, index }) => (
                <li key={index}>
                  <button type="button" aria-pressed={selected === index}
                    className={`flex w-full items-start gap-3 rounded-md px-2.5 py-3 text-left hover:bg-surface-2 ${selected === index ? "bg-primary-soft" : ""}`}
                    onClick={() => selectSegment(index, segment.start)}>
                    <span className="shrink-0 font-mono text-xs leading-5 text-primary">{timestamp(segment.start).slice(0, 8)}</span>
                    <span className="line-clamp-2 whitespace-pre-wrap break-words text-sm text-fg">{segment.text}</span>
                  </button>
                </li>
              ))}
            </ul>
            {!rows.length && <p className="py-4 text-sm text-muted">No matching segments.</p>}
            {lastPage > 0 && (
              <div className="mt-3 flex items-center justify-between gap-2">
                <button type="button" className={button} aria-label="Previous page" disabled={currentPage === 0}
                  onClick={() => setPage(currentPage - 1)}><ChevronLeft aria-hidden className="size-4" /></button>
                <span className="text-sm text-muted">Page {currentPage + 1} of {lastPage + 1}</span>
                <button type="button" className={button} aria-label="Next page" disabled={currentPage === lastPage}
                  onClick={() => setPage(currentPage + 1)}><ChevronRight aria-hidden className="size-4" /></button>
              </div>
            )}
          </section>
          <section aria-label="Edit selected segment" className="min-w-0 rounded-xl border border-line bg-surface p-4 sm:p-5">
            {mediaUrl ? (
              source?.mime.startsWith("video/") ? (
                <video ref={attachPlayer} controls preload="metadata" className="mb-4 max-h-60 w-full rounded-lg"
                  src={mediaUrl} onLoadedMetadata={positionPlayer} />
              ) : <audio ref={attachPlayer} className="mb-4 w-full" controls preload="metadata" src={mediaUrl} onLoadedMetadata={positionPlayer} />
            ) : preview && (
              <button type="button" disabled={mediaLoading} className={`${button} mb-4`} onClick={() => void loadRecording()}>
                <AudioLines aria-hidden className="size-4" /> {mediaLoading ? "Loading recording…" : "Load recording"}
              </button>
            )}
            {current && <SegmentEditor key={`${selected}:${current.start}:${current.end}:${current.text}`}
              segment={current} index={selected} onSave={apply} />}
            <p className="mt-3 text-xs text-muted">Download or export your edits before leaving this page.</p>
          </section>
        </div>
      )}
    </div>
  );
}
