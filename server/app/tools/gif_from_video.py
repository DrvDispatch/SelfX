"""gif-from-video: turn a slice of a video into a high-quality animated GIF (or WebP)."""

from ._media import guard_output_size, probe, validate_time
from .base import Tool, ToolContext, ToolError
from .registry import register

# Rough ceiling on decoded output pixels (out_width * out_height * frames). A GIF
# stores ~1 byte/pixel worst case, so ~250M pixels ~= a few hundred MB — anything
# past this (e.g. 1920x1080@30 for 60s) is rejected before palettegen blows up.
_MAX_GIF_PIXELS = 250_000_000

_DITHERS = ["sierra2_4a", "floyd_steinberg", "bayer", "none"]
_STATS_MODES = ["full", "diff"]
_OUTPUT_FORMATS = ["gif", "webp"]


@register
class GifFromVideo(Tool):
    slug = "gif-from-video"
    name = "Video to GIF"
    category = "media"
    description = "Convert a section of a video into an animated GIF (or WebP) with a good palette."
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
            "output_format": {
                "type": "string",
                "title": "Output format",
                "description": "GIF (universal) or animated WebP (smaller, 24-bit colour).",
                "enum": _OUTPUT_FORMATS,
                "default": "gif",
            },
            "max_colors": {
                "type": "integer",
                "title": "Max colours (GIF)",
                "description": "Fewer colours = smaller file. GIF only.",
                "minimum": 2,
                "maximum": 256,
                "default": 256,
            },
            "stats_mode": {
                "type": "string",
                "title": "Palette mode (GIF)",
                "description": "'diff' favours moving areas — better for motion-heavy clips.",
                "enum": _STATS_MODES,
                "default": "full",
            },
            "dither": {
                "type": "string",
                "title": "Dither (GIF)",
                "description": "sierra2_4a is smoothest; bayer/none give smaller files.",
                "enum": _DITHERS,
                "default": "sierra2_4a",
            },
            "bayer_scale": {
                "type": "integer",
                "title": "Bayer scale",
                "description": "Only used with the bayer dither (0 = fine, 5 = coarse).",
                "minimum": 0,
                "maximum": 5,
                "default": 2,
            },
            "loop": {
                "type": "integer",
                "title": "Loop count",
                "description": "0 = loop forever, 1+ = play that many extra times.",
                "minimum": 0,
                "maximum": 1000,
                "default": 0,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        start = validate_time(ctx.params.get("start", "0"), "start")
        duration = float(ctx.params.get("duration", 5))
        fps = int(ctx.params.get("fps", 12))
        width = int(ctx.params.get("width", 480))
        loop = self._clamp_int(ctx.params.get("loop"), 0, 1000, 0)
        out_fmt = str(ctx.params.get("output_format", "gif"))
        if out_fmt not in _OUTPUT_FORMATS:
            out_fmt = "gif"
        src = ctx.input_paths[0]
        out = ctx.output_dir / f"{src.stem}.{out_fmt}"

        # Reject a request that would produce a pathologically large output before we
        # spend minutes on palettegen. Estimate output height from the source aspect.
        info = probe(ctx, src)
        if info["width"] and info["height"] and info["width"] > 0:
            out_h = max(1, round(width * info["height"] / info["width"]))
        else:
            out_h = max(1, round(width * 9 / 16))
        est_pixels = width * out_h * max(1, round(fps * duration))
        if est_pixels > _MAX_GIF_PIXELS:
            raise ToolError(
                "these settings would produce a very large file — reduce the width, "
                "FPS, or duration (or try a shorter clip)"
            )

        ctx.progress(0.3, "building " + out_fmt.upper())
        if out_fmt == "webp":
            vf = f"fps={fps},scale={width}:-1:flags=lanczos"
            enc = ["-vf", vf, "-c:v", "libwebp", "-loop", str(loop), "-lossless", "0"]
        else:
            enc = ["-vf", self._gif_filter(ctx.params, fps, width), "-loop", str(loop)]

        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y",
            "-ss", start, "-t", str(duration), "-i", str(src),
            *enc, str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError(f"{out_fmt.upper()} creation failed — check the start time and duration")
        guard_output_size(out, out_fmt.upper())
        ctx.progress(1.0, "done")

    def _gif_filter(self, params: dict, fps: int, width: int) -> str:
        max_colors = self._clamp_int(params.get("max_colors"), 2, 256, 256)
        stats_mode = str(params.get("stats_mode", "full"))
        if stats_mode not in _STATS_MODES:
            stats_mode = "full"
        dither = str(params.get("dither", "sierra2_4a"))
        if dither not in _DITHERS:
            dither = "sierra2_4a"
        palettegen = f"palettegen=max_colors={max_colors}:stats_mode={stats_mode}"
        paletteuse = f"paletteuse=dither={dither}"
        if dither == "bayer":
            paletteuse += f":bayer_scale={self._clamp_int(params.get('bayer_scale'), 0, 5, 2)}"
        return (f"fps={fps},scale={width}:-1:flags=lanczos,split[s0][s1];"
                f"[s0]{palettegen}[p];[s1][p]{paletteuse}")

    @staticmethod
    def _clamp_int(value, lo: int, hi: int, default: int) -> int:
        try:
            if value in (None, ""):
                return default
            return max(lo, min(hi, int(value)))
        except (TypeError, ValueError):
            return default
