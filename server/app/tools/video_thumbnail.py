"""video-thumbnail: grab a single frame from a video as a JPEG."""

from ._media import validate_time
from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class VideoThumbnail(Tool):
    slug = "video-thumbnail"
    name = "Video thumbnail"
    category = "media"
    description = "Capture a single frame from a video at a chosen time as a JPEG image."
    accepts = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "time": {
                "type": "string",
                "title": "Timestamp",
                "description": "When to grab the frame (seconds or HH:MM:SS)",
                "default": "00:00:01",
                "maxLength": 12,
            },
            "width": {
                "type": "integer",
                "title": "Max width (px)",
                "description": "Optionally cap the output width so a 4K frame isn't huge.",
                "minimum": 16,
                "maximum": 7680,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        time = validate_time(ctx.params.get("time", "00:00:01") or "00:00:01", "timestamp")
        src = ctx.input_paths[0]
        out = ctx.output_dir / f"{src.stem}-thumb.jpg"

        scale = []
        width = ctx.params.get("width")
        if width is not None:
            # -2 keeps the aspect ratio while forcing an even height for the encoder.
            scale = ["-vf", f"scale={int(width)}:-2"]

        ctx.progress(0.4, "capturing frame")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y",
            "-ss", time, "-i", str(src), "-frames:v", "1", "-an", "-sn",
            *scale, "-q:v", "2", str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("could not capture a frame — the timestamp may be past the end")
        ctx.progress(1.0, "done")
