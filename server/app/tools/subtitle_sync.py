"""subtitle-sync: auto-align an out-of-sync subtitle file to a video/audio track (ffsubsync)."""

from ..config import settings
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
    params_schema = {"type": "object", "properties": {}}

    def run(self, ctx: ToolContext) -> None:
        ref = sub = None
        for p in ctx.input_paths:
            ext = p.suffix.lower()
            if ext in _SUB_EXT and sub is None:
                sub = p
            elif ext in _REF_EXT and ref is None:
                ref = p
        if ref is None or sub is None:
            raise ToolError(
                "please provide exactly one subtitle file (.srt/.vtt/.ass) and one "
                "video or audio file to sync against"
            )
        out = ctx.output_dir / f"{sub.stem}-synced{sub.suffix}"
        ctx.progress(0.3, "analysing audio and aligning subtitles")
        ctx.run_cmd(["ffsubsync", str(ref), "-i", str(sub), "-o", str(out)],
                    timeout=min(settings.job_timeout_seconds, 600))
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("could not synchronize — the audio may lack clear speech")
        ctx.progress(1.0, "done")
