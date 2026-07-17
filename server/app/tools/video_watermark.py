"""video-watermark: overlay a logo/image onto a video (FFmpeg)."""

from ._media import guard_output_size
from .base import Tool, ToolContext, ToolError
from .registry import register

_VIDEO = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg"]
_IMAGE = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"]
_POS = {
    "top-left": "{m}:{m}",
    "top-right": "main_w-overlay_w-{m}:{m}",
    "bottom-left": "{m}:main_h-overlay_h-{m}",
    "bottom-right": "main_w-overlay_w-{m}:main_h-overlay_h-{m}",
    "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
}


@register
class VideoWatermark(Tool):
    slug = "video-watermark"
    name = "Watermark video"
    category = "media"
    description = "Overlay a logo/image onto a video. Attach the video and the watermark image."
    accepts = _VIDEO + _IMAGE
    multi_file = True
    min_files = 2
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "position": {
                "type": "string", "title": "Position",
                "enum": ["top-left", "top-right", "bottom-left", "bottom-right", "center"],
                "default": "bottom-right",
            },
            "width": {"type": "integer", "title": "Watermark width (px)", "minimum": 16, "maximum": 4096, "default": 200},
            "opacity": {"type": "number", "title": "Opacity", "minimum": 0.05, "maximum": 1, "default": 0.8},
            "margin": {"type": "integer", "title": "Margin (px)", "minimum": 0, "maximum": 500, "default": 16},
        },
    }

    def run(self, ctx: ToolContext) -> None:
        video = next((p for p in ctx.input_paths if p.suffix.lower() in _VIDEO), None)
        image = next((p for p in ctx.input_paths if p.suffix.lower() in _IMAGE), None)
        if video is None or image is None:
            raise ToolError("attach one video and one watermark image")

        width = int(ctx.params.get("width", 200))
        try:
            opacity = max(0.05, min(1.0, float(ctx.params.get("opacity", 0.8))))
        except (TypeError, ValueError):
            opacity = 0.8
        margin = max(0, int(ctx.params.get("margin", 16)))
        pos = _POS.get(str(ctx.params.get("position", "bottom-right")), _POS["bottom-right"]).format(m=margin)

        fc = (f"[1:v]scale={width}:-1,format=rgba,colorchannelmixer=aa={opacity}[wm];"
              f"[0:v][wm]overlay={pos}[v]")

        out = ctx.output_dir / f"{video.stem}-watermarked.mp4"
        ctx.progress(0.3, "applying watermark")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(video), "-i", str(image),
            "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-movflags", "+faststart", str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("watermark failed — check the image is valid")
        guard_output_size(out, "watermarked video")
        ctx.progress(1.0, "done")
