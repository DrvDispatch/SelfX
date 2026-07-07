"""gif-from-video: turn a slice of a video into a high-quality animated GIF."""

from ._media import guard_output_size, probe, validate_time
from .base import Tool, ToolContext, ToolError
from .registry import register

# Rough ceiling on decoded output pixels (out_width * out_height * frames). A GIF
# stores ~1 byte/pixel worst case, so ~250M pixels ~= a few hundred MB — anything
# past this (e.g. 1920x1080@30 for 60s) is rejected before palettegen blows up.
_MAX_GIF_PIXELS = 250_000_000


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
        start = validate_time(ctx.params.get("start", "0"), "start")
        duration = float(ctx.params.get("duration", 5))
        fps = int(ctx.params.get("fps", 12))
        width = int(ctx.params.get("width", 480))
        src = ctx.input_paths[0]
        out = ctx.output_dir / f"{src.stem}.gif"

        # Reject a request that would produce a pathologically large GIF before we
        # spend minutes on palettegen. Estimate output height from the source aspect.
        info = probe(ctx, src)
        if info["width"] and info["height"] and info["width"] > 0:
            out_h = max(1, round(width * info["height"] / info["width"]))
        else:
            out_h = max(1, round(width * 9 / 16))
        est_pixels = width * out_h * max(1, round(fps * duration))
        if est_pixels > _MAX_GIF_PIXELS:
            raise ToolError(
                "these settings would produce a very large GIF — reduce the width, "
                "FPS, or duration (or try a shorter clip)"
            )

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
        guard_output_size(out, "GIF")
        ctx.progress(1.0, "done")
