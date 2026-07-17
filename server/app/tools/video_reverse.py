"""video-reverse: play a video (and its audio) backwards (FFmpeg)."""

from ._media import guard_output_size, probe
from .base import Tool, ToolContext, ToolError
from .registry import register

_VIDEO = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg"]


@register
class VideoReverse(Tool):
    slug = "video-reverse"
    name = "Reverse video"
    category = "media"
    description = "Play a clip backwards (audio too). Best for short clips — the whole clip is buffered."
    accepts = _VIDEO
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "keep_audio": {
                "type": "boolean",
                "title": "Reverse audio too",
                "description": "Off = silent reversed video.",
                "default": True,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        keep_audio = bool(ctx.params.get("keep_audio", True)) and probe(ctx, src)["audio"]
        out = ctx.output_dir / f"{src.stem}-reversed.mp4"

        if keep_audio:
            fc = "[0:v]reverse[v];[0:a]areverse[a]"
            maps = ["-map", "[v]", "-map", "[a]", "-c:a", "aac"]
        else:
            fc = "[0:v]reverse[v]"
            maps = ["-map", "[v]", "-an"]

        ctx.progress(0.3, "reversing")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
            "-filter_complex", fc, *maps,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-movflags", "+faststart", str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("reverse failed — the file may not be a valid video")
        guard_output_size(out, "reversed video")
        ctx.progress(1.0, "done")
