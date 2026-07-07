"""video-trim: cut a clip out of a video with FFmpeg (accurate re-encode)."""

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class VideoTrim(Tool):
    slug = "video-trim"
    name = "Trim video"
    category = "media"
    description = "Cut a clip from a video between a start time and a duration."
    accepts = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "start": {
                "type": "string",
                "title": "Start",
                "description": "Start time (seconds or HH:MM:SS)",
                "default": "0",
                "maxLength": 12,
            },
            "duration": {
                "type": "number",
                "title": "Duration (seconds)",
                "minimum": 0.1,
                "maximum": 86400,
            },
        },
        "required": ["duration"],
    }

    def run(self, ctx: ToolContext) -> None:
        start = str(ctx.params.get("start", "0")).strip() or "0"
        duration = float(ctx.params["duration"])
        src = ctx.input_paths[0]
        out = ctx.output_dir / f"{src.stem}-clip.mp4"
        ctx.progress(0.3, "trimming")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y",
            "-ss", start, "-i", str(src), "-t", str(duration),
            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
            "-movflags", "+faststart", str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("trim failed — check the start time is within the video")
        ctx.progress(1.0, "done")
