"""video-mute: strip the audio track from a video (FFmpeg, lossless copy)."""

from ._media import guard_output_size
from .base import Tool, ToolContext, ToolError
from .registry import register

_VIDEO = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg"]


@register
class VideoMute(Tool):
    slug = "video-mute"
    name = "Mute video"
    category = "media"
    description = "Remove the audio track from a video, keeping the picture untouched (fast, lossless)."
    accepts = _VIDEO
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {"type": "object", "properties": {}}

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        out = ctx.output_dir / f"{src.stem}-muted{src.suffix.lower() or '.mp4'}"
        ctx.progress(0.3, "removing audio")
        # copy the video stream, drop audio — near-instant, no quality loss
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
            "-c", "copy", "-an", str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("mute failed — the file may not be a valid video")
        guard_output_size(out, "muted video")
        ctx.progress(1.0, "done")
