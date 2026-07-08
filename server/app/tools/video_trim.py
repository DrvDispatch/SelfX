"""video-trim: cut a clip out of a video with FFmpeg (accurate re-encode, or fast copy)."""

from ._media import guard_output_size, validate_time
from .base import Tool, ToolContext, ToolError
from .registry import register

# libx264 -preset choices, exposed so a CPU-bound user can trade speed for size.
_X264_SPEEDS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
                "medium", "slow", "slower", "veryslow"]


def _to_seconds(value: str) -> float:
    """Convert an already-validated time string (seconds or [HH:]MM:SS[.ms]) to seconds."""
    value = value.strip()
    if ":" in value:
        secs = 0.0
        for part in value.split(":"):
            secs = secs * 60 + float(part or 0)
        return secs
    return float(value or 0)


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
            "end": {
                "type": "string",
                "title": "End (alternative to duration)",
                "description": "End time (seconds or HH:MM:SS). Used only when Duration is blank.",
                "maxLength": 12,
            },
            "copy": {
                "type": "boolean",
                "title": "Fast lossless cut",
                "description": "Copy streams without re-encoding (near-instant, but cuts "
                               "snap to the nearest keyframe so the start may be slightly off).",
                "default": False,
            },
            "crf": {
                "type": "integer",
                "title": "Quality (CRF)",
                "description": "Lower = better/larger. Only used when re-encoding (0-51).",
                "minimum": 0,
                "maximum": 51,
            },
            "speed": {
                "type": "string",
                "title": "Encoder speed",
                "description": "Faster = quicker encode, larger file. Only used when re-encoding.",
                "enum": _X264_SPEEDS,
            },
        },
        "required": [],
    }

    def run(self, ctx: ToolContext) -> None:
        start = validate_time(ctx.params.get("start", "0"), "start")
        src = ctx.input_paths[0]
        copy = bool(ctx.params.get("copy", False))

        # Duration wins; otherwise derive it from an explicit end time.
        raw_duration = ctx.params.get("duration")
        if raw_duration not in (None, ""):
            duration = float(raw_duration)
        elif ctx.params.get("end") not in (None, ""):
            end = validate_time(ctx.params.get("end"), "end")
            duration = _to_seconds(end) - _to_seconds(start)
            if duration <= 0:
                raise ToolError("the end time must be after the start time")
        else:
            raise ToolError("please set a duration (or an end time)")

        if copy:
            # Keyframe-aligned stream copy: instant + lossless, keep the source container.
            out = ctx.output_dir / f"{src.stem}-clip{src.suffix.lower() or '.mp4'}"
            enc = ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        else:
            out = ctx.output_dir / f"{src.stem}-clip.mp4"
            speed = str(ctx.params.get("speed") or "veryfast")
            if speed not in _X264_SPEEDS:
                speed = "veryfast"
            enc = ["-c:v", "libx264", "-preset", speed]
            crf = ctx.params.get("crf")
            if crf not in (None, ""):
                enc += ["-crf", str(int(crf))]
            enc += ["-c:a", "aac", "-movflags", "+faststart"]

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
