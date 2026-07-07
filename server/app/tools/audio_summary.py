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
            }
        },
    }

    def available(self) -> tuple[bool, str | None]:
        return _ollama.is_available()

    def run(self, ctx: ToolContext) -> None:
        from .transcribe import _get_model

        length = str(ctx.params.get("length", "medium"))
        src = ctx.input_paths[0]
        ctx.progress(0.15, "transcribing audio")
        model = _get_model()
        segments, info = model.transcribe(str(src), vad_filter=True)
        transcript = " ".join(s.text.strip() for s in segments).strip()
        if not transcript:
            raise ToolError("no speech was detected in the recording")

        ctx.progress(0.7, "writing notes with local AI")
        notes = _ollama.chat([
            {"role": "system", "content": "You write clear, structured notes from transcripts."},
            {"role": "user", "content": f"{_PROMPT.get(length, _PROMPT['medium'])}\n\n"
                                        f"Transcript:\n{transcript[:24000]}"},
        ])
        stem = src.stem
        (ctx.output_dir / f"{stem}-notes.txt").write_text(notes, encoding="utf-8")
        (ctx.output_dir / f"{stem}-transcript.txt").write_text(transcript, encoding="utf-8")
        ctx.progress(1.0, "done")
