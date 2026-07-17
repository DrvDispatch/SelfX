"""video-crop: crop a video to a region or a target aspect ratio (FFmpeg)."""

from ._media import guard_output_size
from .base import Tool, ToolContext, ToolError
from .registry import register

_VIDEO = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg"]
# aspect ratio (width / height) for each preset
_ASPECT = {"1:1": 1.0, "4:5": 0.8, "9:16": 9 / 16, "16:9": 16 / 9, "4:3": 4 / 3, "3:4": 3 / 4}


@register
class VideoCrop(Tool):
    slug = "video-crop"
    name = "Crop video"
    category = "media"
    description = "Crop a video to a shape (square, 9:16 for reels/stories, 16:9…) or an exact box."
    accepts = _VIDEO
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "aspect": {
                "type": "string",
                "title": "Crop to",
                "description": "Center-crop to this shape, or 'custom' to set an exact pixel box below.",
                "enum": ["1:1", "4:5", "9:16", "16:9", "4:3", "3:4", "custom"],
                "default": "1:1",
            },
            "x": {"type": "integer", "title": "X offset (custom)", "minimum": 0, "default": 0},
            "y": {"type": "integer", "title": "Y offset (custom)", "minimum": 0, "default": 0},
            "width": {"type": "integer", "title": "Width (custom)", "minimum": 2, "maximum": 8192},
            "height": {"type": "integer", "title": "Height (custom)", "minimum": 2, "maximum": 8192},
        },
    }

    def run(self, ctx: ToolContext) -> None:
        aspect = str(ctx.params.get("aspect", "1:1"))
        src = ctx.input_paths[0]
        if aspect == "custom":
            w, h = ctx.params.get("width"), ctx.params.get("height")
            if not w or not h:
                raise ToolError("set a width and height for a custom crop")
            x = max(0, int(ctx.params.get("x", 0)))
            y = max(0, int(ctx.params.get("y", 0)))
            crop = f"crop={int(w)}:{int(h)}:{x}:{y}"
        else:
            r = _ASPECT.get(aspect, 1.0)
            # largest centered box of ratio r that fits, forced to even dimensions
            crop = f"crop='trunc(min(iw,ih*{r})/2)*2':'trunc(min(ih,iw/{r})/2)*2'"

        out = ctx.output_dir / f"{src.stem}-crop.mp4"
        ctx.progress(0.3, "cropping")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
            "-vf", crop, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-movflags", "+faststart", str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("crop failed — check the region fits inside the video")
        guard_output_size(out, "cropped video")
        ctx.progress(1.0, "done")
