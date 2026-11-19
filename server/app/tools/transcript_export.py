"""Render edited SelfX transcript JSON without speech inference."""

import json
import math

from ._transcript_pdf import export_transcript_pdf
from .base import Tool, ToolContext, ToolError
from .registry import register

_MAX_BYTES = 12 * 1024 * 1024
_MAX_SEGMENTS = 10_000
_MAX_SECONDS = 86_400


def _time(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= _MAX_SECONDS:
        raise ToolError("Transcript timestamps must be between 0 seconds and 24 hours")
    if not math.isfinite(value):
        raise ToolError("Transcript timestamps must be finite")
    return float(value)


def read_transcript(ctx: ToolContext) -> dict:
    with ctx.input_paths[0].open("rb") as source:
        raw = source.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise ToolError("Choose a transcript JSON file under 12 MiB")
    try:
        document = json.loads(raw)
    except (ValueError, RecursionError):
        raise ToolError("Choose valid SelfX transcript JSON") from None
    entries = document.get("segments") if isinstance(document, dict) else None
    if not isinstance(entries, list) or not 1 <= len(entries) <= _MAX_SEGMENTS:
        raise ToolError("A transcript needs between 1 and 10,000 segments")
    segments = []
    previous = 0.0
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
            raise ToolError(f"Segment {index} needs text")
        text = "\n".join(line for line in entry["text"].strip().splitlines() if line.strip())
        if not text or len(text) > 8_000:
            raise ToolError(f"Segment {index} needs between 1 and 8,000 characters")
        start, end = _time(entry.get("start")), _time(entry.get("end"))
        if start < previous or round(end * 1000) <= round(start * 1000):
            raise ToolError(f"Segment {index} has invalid timing or appears out of order")
        segments.append({"start": start, "end": end, "text": text})
        previous = start
    language = document.get("language")
    return {
        "segments": segments,
        "duration": max(segment["end"] for segment in segments),
        "language": language if isinstance(language, str) and len(language) <= 16 else None,
    }


@register
class TranscriptExport(Tool):
    slug = "transcript-export"
    name = "Export edited transcript"
    category = "subtitles"
    description = "Make a timestamped PDF and SRT from an edited SelfX transcript JSON file."
    accepts = [".json"]
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {"title": {"type": "string", "title": "PDF title", "maxLength": 160}},
        "additionalProperties": False,
    }

    def run(self, ctx: ToolContext) -> None:
        export_transcript_pdf(ctx, read_transcript(ctx), include_json=False)
