"""video-trim: cut a clip out of a video with FFmpeg (accurate re-encode, or fast copy)."""

from ._media import guard_output_size, validate_time
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
            "copy": {
                "type": "boolean",
                "title": "Fast lossless cut",
                "description": "Copy streams without re-encoding (near-instant, but cuts "
                               "snap to the nearest keyframe so the start may be slightly off).",
                "default": False,
            },
        },
        "required": ["duration"],
    }

    def run(self, ctx: ToolContext) -> None:
        start = validate_time(ctx.params.get("start", "0"), "start")
        duration = float(ctx.params["duration"])
        src = ctx.input_paths[0]
        copy = bool(ctx.params.get("copy", False))

        if copy:
            # Keyframe-aligned stream copy: instant + lossless, keep the source container.
            out = ctx.output_dir / f"{src.stem}-clip{src.suffix.lower() or '.mp4'}"
            enc = ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        else:
            out = ctx.output_dir / f"{src.stem}-clip.mp4"
            enc = ["-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
                   "-movflags", "+faststart"]

        ctx.progress(0.3, "trimming")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y",
            "-ss", start, "-i", str(src), "-t", str(duration),
            *enc, str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("trim failed — check the start time is within the video")
        guard_output_size(out, "clip")
        ctx.progress(1.0, "done")
