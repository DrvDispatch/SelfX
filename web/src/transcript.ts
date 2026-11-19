export const TRANSCRIPT_MAX_BYTES = 12 * 1024 * 1024;
const MAX_TIME = 24 * 60 * 60;

interface WordTiming {
  start: number;
  end: number;
  word: string;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
  speaker?: string;
  words?: WordTiming[];
}

export interface Transcript {
  schema_version: 1;
  language: string | null;
  duration: number;
  segments: TranscriptSegment[];
}

export type TranscriptFormat = "txt" | "srt" | "vtt" | "json";

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validTime(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= MAX_TIME;
}

export function parseTranscript(text: string): Transcript {
  const raw: unknown = JSON.parse(text);
  if (!record(raw) || !Array.isArray(raw.segments) || !raw.segments.length || raw.segments.length > 10_000) {
    throw new Error("This file is missing a valid transcript.");
  }
  const segments = raw.segments.map((entry: unknown, index): TranscriptSegment => {
    if (!record(entry) || !validTime(entry.start) || !validTime(entry.end) || entry.end < entry.start ||
        typeof entry.text !== "string" || entry.text.length > 8000 || !entry.text.trim()) {
      throw new Error(`Segment ${index + 1} has invalid timing or text.`);
    }
    const segment: TranscriptSegment = { start: entry.start, end: entry.end, text: entry.text };
    if (typeof entry.speaker === "string") segment.speaker = entry.speaker.slice(0, 80);
    if (Array.isArray(entry.words)) {
      segment.words = entry.words.filter((word: unknown): word is WordTiming =>
        record(word) && validTime(word.start) && validTime(word.end) && word.end >= word.start &&
        typeof word.word === "string");
    }
    return segment;
  }).sort((a, b) => a.start - b.start);
  return {
    schema_version: 1,
    language: typeof raw.language === "string" ? raw.language.slice(0, 16) : null,
    duration: Math.max(validTime(raw.duration) ? raw.duration : 0, ...segments.map((segment) => segment.end)),
    segments,
  };
}

export function timestamp(seconds: number, separator = "."): string {
  const ms = Math.round(seconds * 1000);
  const units = [Math.floor(ms / 3_600_000), Math.floor(ms / 60_000) % 60, Math.floor(ms / 1000) % 60];
  return units.map((unit) => String(unit).padStart(2, "0")).join(":") +
    separator + String(ms % 1000).padStart(3, "0");
}

export function editedSegment(
  segments: TranscriptSegment[], index: number, text: string, start: string, end: string,
): TranscriptSegment {
  const begin = Number(start);
  const finish = Number(end);
  if (!start.trim() || !end.trim() || !validTime(begin) || !validTime(finish) ||
      Math.round(finish * 1000) <= Math.round(begin * 1000)) {
    throw new Error("Enter a start time and a later end time, in seconds.");
  }
  if ((index > 0 && begin < segments[index - 1].start) ||
      (index < segments.length - 1 && begin > segments[index + 1].start)) {
    throw new Error("Keep this segment's start time between its neighbors.");
  }
  const clean = text.trim();
  if (!clean || clean.length > 8_000) throw new Error("Enter between 1 and 8,000 characters.");
  const previous = segments[index];
  if (previous.start === begin && previous.end === finish && previous.text === clean) return previous;
  return { start: begin, end: finish, text: clean, speaker: previous.speaker };
}

export function exportTranscript(transcript: Transcript, format: TranscriptFormat): string {
  const segments = transcript.segments.map((segment) => ({
    ...segment,
    end: Math.min(MAX_TIME, Math.max(segment.end, (Math.round(segment.start * 1000) + 1) / 1000)),
  }));
  if (format === "json") {
    const duration = Math.max(transcript.duration, ...segments.map((segment) => segment.end));
    return JSON.stringify({ ...transcript, duration, segments }, null, 2);
  }
  if (format === "txt") return segments.map((segment) => segment.text).join("\n\n") + "\n";
  const comma = format === "srt" ? "," : ".";
  const cues = segments.map((segment, index) => {
    const time = `${timestamp(segment.start, comma)} --> ${timestamp(segment.end, comma)}`;
    const escaped = format === "vtt"
      ? segment.text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      : segment.text;
    const text = escaped.split("\n").filter((line) => line.trim()).join("\n");
    return format === "srt" ? `${index + 1}\n${time}\n${text}` : `${time}\n${text}`;
  });
  return (format === "vtt" ? "WEBVTT\n\n" : "") + cues.join("\n\n") + "\n";
}
