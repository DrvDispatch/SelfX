"""video-resize: scale a video to a target resolution while keeping aspect ratio (FFmpeg)."""

from ._media import guard_output_size
from .base import Tool, ToolContext, ToolError
from .registry import register

_VIDEO = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg"]
_HEIGHTS = {"2160": 2160, "1440": 1440, "1080": 1080, "720": 720, "480": 480, "360": 360, "240": 240}


@register
class VideoResize(Tool):
    slug = "video-resize"
    name = "Resize video"
    category = "media"
    description = "Scale a video down (or up) to a standard resolution, keeping the aspect ratio."
    accepts = _VIDEO
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "resolution": {
                "type": "string",
                "title": "Resolution (height)",
                "description": "Scales to this height, preserving aspect ratio.",
                "enum": ["2160", "1440", "1080", "720", "480", "360", "240"],
                "default": "720",
            },
            "width": {
                "type": "integer",
                "title": "Exact width (optional)",
                "description": "Overrides Resolution: scales to this width, height auto.",
                "minimum": 16,
                "maximum": 8192,
            },
            "crf": {
                "type": "integer",
                "title": "Quality (CRF)",
                "description": "Lower = better/larger (0-51).",
                "minimum": 0,
                "maximum": 51,
                "default": 22,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        width = ctx.params.get("width")
        if width not in (None, ""):
            vf = f"scale={int(width)}:-2"
        else:
            h = _HEIGHTS.get(str(ctx.params.get("resolution", "720")), 720)
            vf = f"scale=-2:{h}"
        crf = int(ctx.params.get("crf", 22))
        out = ctx.output_dir / f"{src.stem}-resized.mp4"
        ctx.progress(0.3, "resizing")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
            "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-c:a", "aac", "-movflags", "+faststart", str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("resize failed — the file may not be a valid video")
        guard_output_size(out, "resized video")
        ctx.progress(1.0, "done")
