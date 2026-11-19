import type { ToolInfo } from "./types";

const aliases: Record<string, string> = {
  "pdf-merge": "combine join PDFs into one document",
  "pdf-organize": "rearrange reorder move delete remove extract PDF pages fix page sequence",
  "pdf-compress": "shrink make PDF smaller reduce file size",
  "ocr-pdf": "scan searchable scanned PDF recognize text",
  "image-convert": "convert photo change image format HEIC JPG JPEG PNG WebP AVIF",
  "image-optimize": "compress photo make image smaller reduce file size",
  "image-remove-bg": "remove photo background transparent cutout",
  "image-to-text": "extract copy text from image screenshot OCR",
  "media-convert": "convert audio video MP3 MP4 WAV WebM change format",
  "video-trim": "cut clip shorten video",
  "video-target-size": "shrink mp4 under size maximum fit upload limit compress video megabytes email attachment",
  "video-crop": "reframe portrait landscape vertical video",
  "video-burn-subtitles": "add captions embed subtitles in video",
  "subtitle-cleanup": "fix subtitles remove duplicate captions shift offset subtitle timestamps SRT VTT tidy normalize",
  "transcribe": "speech to text recording transcript automatic captions create subtitles SRT VTT",
  "transcript-export": "turn edited transcript json into PDF SRT captions export regenerate",
  "audio-summary": "meeting notes lecture notes summarize recording transcription",
  "pdf-to-markdown": "extract PDF as Markdown",
  "qr-generate": "create QR code for link",
};

function words(text: string) {
  return text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
}

export function matchesSearch(text: string, query: string) {
  const terms = words(text);
  return words(query).every((term) => terms.some((word) => word.startsWith(term)));
}

export function toolSearchText(tool: ToolInfo) {
  return [tool.name, tool.slug, tool.description, tool.category, aliases[tool.slug]].join(" ");
}

export function acceptsFilename(name: string, extensions: string[]) {
  const lower = name.toLowerCase();
  return extensions.length === 0 || extensions.some((extension) => lower.endsWith(extension.toLowerCase()));
}

export function fileToolMode(tool: ToolInfo, files: File[]) {
  if (!tool.available || tool.min_files === 0 || files.length < tool.min_files) return null;
  if (!files.every((file) => acceptsFilename(file.name, tool.accepts))) return null;
  if (tool.multi_file || files.length === 1) return "single";
  return tool.min_files === 1 ? "batch" : null;
}
