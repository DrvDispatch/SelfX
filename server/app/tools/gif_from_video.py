"""gif-from-video: turn a slice of a video into a high-quality animated GIF."""

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class GifFromVideo(Tool):
    slug = "gif-from-video"
    name = "Video to GIF"
    category = "media"
    description = "Convert a section of a video into an animated GIF with a good palette."
    accepts = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".gif"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "start": {"type": "string", "title": "Start", "default": "0", "maxLength": 12},
            "duration": {"type": "number", "title": "Duration (s)", "minimum": 0.1,
                         "maximum": 60, "default": 5},
            "fps": {"type": "integer", "title": "FPS", "minimum": 5, "maximum": 30, "default": 12},
            "width": {"type": "integer", "title": "Width (px)", "minimum": 80,
                      "maximum": 1920, "default": 480},
        },
    }

    def run(self, ctx: ToolContext) -> None:
        start = str(ctx.params.get("start", "0")).strip() or "0"
        duration = float(ctx.params.get("duration", 5))
        fps = int(ctx.params.get("fps", 12))
        width = int(ctx.params.get("width", 480))
        src = ctx.input_paths[0]
        out = ctx.output_dir / f"{src.stem}.gif"
        vf = (f"fps={fps},scale={width}:-1:flags=lanczos,split[s0][s1];"
              f"[s0]palettegen[p];[s1][p]paletteuse")
        ctx.progress(0.3, "building GIF")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y",
            "-ss", start, "-t", str(duration), "-i", str(src),
            "-vf", vf, str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("GIF creation failed — check the start time and duration")
        ctx.progress(1.0, "done")
