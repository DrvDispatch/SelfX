"""subtitle-sync: auto-align an out-of-sync subtitle file to a video/audio track (ffsubsync)."""

import shutil

from ..config import settings
from ._subtitles import detect_encoding, validate_has_cues
from .base import Tool, ToolContext, ToolError
from .registry import register

_SUB_EXT = {".srt", ".vtt", ".ass", ".ssa"}
_REF_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v",
            ".mp3", ".wav", ".flac", ".aac", ".m4a", ".opus", ".ogg"}


@register
class SubtitleSync(Tool):
    slug = "subtitle-sync"
    name = "Sync subtitles"
    category = "subtitles"
    description = "Automatically shift/stretch a subtitle file so it lines up with a video or audio track."
    accepts = sorted(_SUB_EXT | _REF_EXT)
    multi_file = True
    min_files = 2
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "encoding": {
                "type": "string",
                "title": "Subtitle encoding",
                "description": "Override the detected subtitle charset (e.g. cp1256, cp1251, gbk). Leave blank to auto-detect.",
                "default": "",
                "maxLength": 32,
            },
            "gss": {
                "type": "boolean",
                "title": "Robust search (large offsets)",
                "description": "Use golden-section search — more robust when the offset is large or unknown. Slightly slower.",
                "default": False,
            },
            "max_offset_seconds": {
                "type": "integer",
                "title": "Max offset (seconds)",
                "description": "Largest shift the aligner may apply. 0 keeps the engine default (60s).",
                "minimum": 0,
                "maximum": 3600,
                "default": 0,
            },
            "vad": {
                "type": "string",
                "title": "Speech detector",
                "description": "Voice-activity detector used to find speech. 'silero' is often more accurate than the default. Leave as 'default' to keep the engine default.",
                "enum": [
                    "default",
                    "webrtc",
                    "silero",
                    "auditok",
                    "subs_then_webrtc",
                    "subs_then_silero",
                    "subs_then_auditok",
                ],
                "default": "default",
            },
        },
    }

    _VAD_CHOICES = {
        "webrtc",
        "silero",
        "auditok",
        "subs_then_webrtc",
        "subs_then_silero",
        "subs_then_auditok",
    }

    def available(self) -> tuple[bool, str | None]:
        if shutil.which("ffsubsync"):
            return True, None
        return False, "the subtitle-sync engine (ffsubsync) is not installed"

    def run(self, ctx: ToolContext) -> None:
        subs = [p for p in ctx.input_paths if p.suffix.lower() in _SUB_EXT]
        media = [p for p in ctx.input_paths if p.suffix.lower() in _REF_EXT]
        if not subs:
            raise ToolError(
                "please provide a subtitle file (.srt/.vtt/.ass) to synchronize"
            )
        sub = subs[0]
        if media:
            ref = media[0]
        elif len(subs) >= 2:
            # ffsubsync can align a subtitle against a known-good REFERENCE
            # subtitle (fast, no audio decoding) — enable that instead of erroring.
            ref = subs[1]
        else:
            raise ToolError(
                "please provide a video or audio file (or a second, correctly-synced "
                "subtitle) to sync against"
            )

        override = str(ctx.params.get("encoding", "") or "").strip() or None
        enc = override or detect_encoding(sub)

        out = ctx.output_dir / f"{sub.stem}-synced{sub.suffix}"
        ctx.progress(0.3, "analysing audio and aligning subtitles")
        argv = ["ffsubsync", str(ref), "-i", str(sub), "-o", str(out)]
        if enc:
            # Handle non-UTF-8 subs (CP1256/CP1251/GBK/…) and normalize output.
            argv += ["--encoding", enc]
        argv += ["--output-encoding", "utf-8"]

        # Optional alignment tuning (all opt-in; defaults reproduce prior behavior).
        if bool(ctx.params.get("gss", False)):
            argv += ["--gss"]
        try:
            max_off = int(ctx.params.get("max_offset_seconds", 0) or 0)
        except (TypeError, ValueError):
            max_off = 0
        max_off = max(0, min(max_off, 3600))
        if max_off > 0:
            argv += ["--max-offset-seconds", str(max_off)]
        vad = str(ctx.params.get("vad", "default") or "default").strip().lower()
        if vad in self._VAD_CHOICES:
            argv += ["--vad", vad]

        ctx.run_cmd(argv, timeout=min(settings.job_timeout_seconds, 600))
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("could not synchronize — the audio may lack clear speech")
        # Validate SEMANTIC output: the synced file still has real cues.
        validate_has_cues(out)
        ctx.progress(1.0, "done")
