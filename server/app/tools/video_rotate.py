"""video-rotate: rotate or flip a video (FFmpeg)."""

from ._media import guard_output_size
from .base import Tool, ToolContext, ToolError
from .registry import register

_VIDEO = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg"]
_TRANSFORMS = {
    "90cw": "transpose=1",
    "90ccw": "transpose=2",
    "180": "transpose=1,transpose=1",
    "flip-h": "hflip",
    "flip-v": "vflip",
}


@register
class VideoRotate(Tool):
    slug = "video-rotate"
    name = "Rotate / flip video"
    category = "media"
    description = "Rotate a video 90°/180° or mirror it horizontally / vertically."
    accepts = _VIDEO
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "transform": {
                "type": "string",
                "title": "Transform",
                "enum": ["90cw", "90ccw", "180", "flip-h", "flip-v"],
                "default": "90cw",
            },
        },
        "required": ["transform"],
    }

    def run(self, ctx: ToolContext) -> None:
        vf = _TRANSFORMS.get(str(ctx.params.get("transform", "90cw")))
        if not vf:
            raise ToolError("unknown transform")
        src = ctx.input_paths[0]
        out = ctx.output_dir / f"{src.stem}-rotated.mp4"
        ctx.progress(0.3, "rotating")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
            "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-movflags", "+faststart", str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("rotate failed — the file may not be a valid video")
        guard_output_size(out, "rotated video")
        ctx.progress(1.0, "done")
