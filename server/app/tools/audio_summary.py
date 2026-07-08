"""audio-summary: transcribe audio/video and summarize it into meeting-style notes.

Chains local Whisper (transcription) into the local LLM (summary) — no diarization
(who-said-what needs a GPU + HuggingFace token; see the roadmap).
"""

from . import _ollama
from .base import Tool, ToolContext, ToolError
from .registry import register

_PROMPT = {
    "short": "Summarize this transcript in 2-3 sentences.",
    "medium": "Summarize this transcript into concise notes: key points as bullets.",
    "detailed": "Write detailed meeting notes from this transcript: a summary, key points "
                "as bullets, decisions made, and action items.",
}

# Map-reduce sizing for long recordings (a 2-hour meeting far exceeds one context).
_CHUNK_CHARS = 10_000
_MAX_CHUNKS = 12


@register
class AudioSummary(Tool):
    slug = "audio-summary"
    name = "Summarize audio (notes)"
    category = "ai"
    description = "Transcribe a recording and turn it into summary notes with key points and action items."
    accepts = [".mp3", ".wav", ".flac", ".aac", ".ogg", ".opus", ".m4a",
               ".mp4", ".mov", ".mkv", ".webm", ".m4v"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "length": {
                "type": "string",
                "title": "Detail",
                "enum": ["short", "medium", "detailed"],
                "default": "medium",
            },
            "language": {
                "type": "string",
                "title": "Language",
                "description": "ISO code (e.g. en, de, fr) or 'auto' to detect",
                "default": "auto",
                "maxLength": 10,
            },
            "include_timestamps": {
                "type": "boolean",
                "title": "Timestamps in transcript",
                "description": "Prefix each line of the saved transcript with its time so notes can cite it.",
                "default": False,
            },
        },
    }

    def available(self) -> tuple[bool, str | None]:
        return _ollama.is_available()

    def run(self, ctx: ToolContext) -> None:
        from .transcribe import _get_model, _resolve_language, _ts

        length = str(ctx.params.get("length", "medium"))
        instruction = _PROMPT.get(length, _PROMPT["medium"])
        language = str(ctx.params.get("language", "auto"))
        include_timestamps = bool(ctx.params.get("include_timestamps", False))
        lang = _resolve_language(language)  # validates; raises a clear ToolError
        src = ctx.input_paths[0]
        ctx.progress(0.15, "transcribing audio")
        model = _get_model("large-v3-turbo")
        segments, info = model.transcribe(str(src), language=lang, vad_filter=True)
        segs = list(segments)
        transcript = " ".join(s.text.strip() for s in segs).strip()
        if not transcript:
            raise ToolError("no speech was detected in the recording")

        ctx.progress(0.7, "writing notes with local AI")
        # Map-reduce long transcripts instead of silently dropping the back half.
        chunks = [transcript[i:i + _CHUNK_CHARS] for i in range(0, len(transcript), _CHUNK_CHARS)]
        truncated = len(chunks) > _MAX_CHUNKS
        if truncated:
            chunks = chunks[:_MAX_CHUNKS]

        if len(chunks) <= 1:
            notes = _ollama.chat([
                {"role": "system", "content": "You write clear, structured notes from transcripts."},
                {"role": "user", "content": f"{instruction}\n\nTranscript:\n{transcript}"},
            ])
        else:
            partials = []
            for i, chunk in enumerate(chunks):
                ctx.progress(0.7 + 0.2 * (i / len(chunks)), f"summarizing part {i + 1}/{len(chunks)}")
                part = _ollama.chat([
                    {"role": "system", "content": "You write clear, structured notes from transcripts."},
                    {"role": "user", "content":
                        f"This is part {i + 1} of {len(chunks)} of a meeting transcript. List the "
                        f"key points, decisions, and action items mentioned in THIS part.\n\n{chunk}"},
                ])
                partials.append(part)
            ctx.progress(0.9, "combining notes")
            combined = "\n\n".join(partials)
            notes = _ollama.chat([
                {"role": "system", "content": "You write clear, structured notes from transcripts."},
                {"role": "user", "content":
                    f"{instruction}\n\nThe text below is notes from consecutive parts of ONE "
                    f"recording. Merge them into one coherent set of notes without duplication.\n\n{combined}"},
            ])

        if truncated:
            notes += "\n\n[Note: the recording was long; these notes cover only its first portion.]"

        stem = src.stem
        if include_timestamps:
            transcript_out = "\n".join(
                f"[{_ts(s.start or 0, '.')}] {s.text.strip()}" for s in segs
            )
        else:
            transcript_out = transcript
        (ctx.output_dir / f"{stem}-notes.txt").write_text(notes, encoding="utf-8")
        (ctx.output_dir / f"{stem}-transcript.txt").write_text(transcript_out, encoding="utf-8")
        ctx.progress(1.0, "done")
