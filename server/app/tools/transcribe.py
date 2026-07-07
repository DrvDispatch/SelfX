"""transcribe: speech-to-text for audio/video with faster-whisper (SPEC §8).

The model is loaded once per worker process and cached. First use downloads the
model weights, so the first job is slower.
"""

from .base import Tool, ToolContext, ToolError
from .registry import register
from ..config import settings

_MODEL = None  # lazily-loaded WhisperModel, shared across jobs in this worker


def _get_model():
    global _MODEL
    if _MODEL is None:
        try:
            from faster_whisper import WhisperModel
        except Exception:
            raise ToolError("the transcription engine is not available on this server") from None
        _MODEL = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute,
        )
    return _MODEL


def _ts(seconds: float, sep: str) -> str:
    """Format seconds as HH:MM:SS,mmm (srt, sep=',') or HH:MM:SS.mmm (vtt, sep='.')."""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


@register
class Transcribe(Tool):
    slug = "transcribe"
    name = "Transcribe audio / video"
    category = "ai"
    description = "Transcribe speech from an audio or video file to text or subtitles (local Whisper)."
    accepts = [
        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".opus", ".m4a", ".wma", ".aiff",
        ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v",
    ]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "language": {
                "type": "string",
                "title": "Language",
                "description": "ISO code (e.g. en, de, fr) or 'auto' to detect",
                "default": "auto",
                "maxLength": 10,
            },
            "output": {
                "type": "string",
                "title": "Output format",
                "enum": ["txt", "srt", "vtt", "json"],
                "default": "txt",
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        language = str(ctx.params.get("language", "auto")).strip()
        output = str(ctx.params.get("output", "txt"))
        model = _get_model()
        src = ctx.input_paths[0]

        ctx.progress(0.1, "loading model / decoding audio")
        segments, info = model.transcribe(
            str(src),
            language=None if language in ("", "auto") else language,
            vad_filter=True,
        )
        total = getattr(info, "duration", 0) or 0
        segs = []
        for seg in segments:  # generator — consumed lazily, so we can stream progress
            segs.append(seg)
            if total:
                ctx.progress(min(0.95, (seg.end or 0) / total), "transcribing")

        ctx.progress(0.97, f"writing {output}")
        out_path = ctx.output_dir / f"{src.stem}.{output}"
        if output == "txt":
            out_path.write_text("\n".join(s.text.strip() for s in segs), encoding="utf-8")
        elif output == "json":
            import json

            data = {
                "language": getattr(info, "language", None),
                "duration": total,
                "segments": [
                    {"start": s.start, "end": s.end, "text": s.text.strip()} for s in segs
                ],
            }
            out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        elif output in ("srt", "vtt"):
            sep = "," if output == "srt" else "."
            lines = []
            if output == "vtt":
                lines.append("WEBVTT\n")
            for i, s in enumerate(segs, 1):
                if output == "srt":
                    lines.append(str(i))
                lines.append(f"{_ts(s.start or 0, sep)} --> {_ts(s.end or 0, sep)}")
                lines.append(s.text.strip())
                lines.append("")
            out_path.write_text("\n".join(lines), encoding="utf-8")
        else:
            raise ToolError(f"unsupported output format '{output}'")
        ctx.progress(1.0, "done")
