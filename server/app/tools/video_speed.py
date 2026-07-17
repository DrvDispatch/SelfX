"""video-speed: change playback speed (slow-motion / timelapse) keeping pitch (FFmpeg)."""

from ._media import guard_output_size, probe
from .base import Tool, ToolContext, ToolError
from .registry import register

_VIDEO = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg"]


def _atempo_chain(speed: float) -> str:
    """atempo only accepts 0.5–2.0, so chain filters to reach any factor."""
    parts: list[str] = []
    s = speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s *= 2.0
    parts.append(f"atempo={s:.6f}")
    return ",".join(parts)


@register
class VideoSpeed(Tool):
    slug = "video-speed"
    name = "Change video speed"
    category = "media"
    description = "Speed up or slow down a video (0.25×–4×). Audio pitch is preserved."
    accepts = _VIDEO
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "speed": {
                "type": "number",
                "title": "Speed",
                "description": "2 = twice as fast, 0.5 = half speed (slow-mo).",
                "minimum": 0.25,
                "maximum": 4,
                "default": 2,
            },
        },
        "required": ["speed"],
    }

    def run(self, ctx: ToolContext) -> None:
        try:
            speed = float(ctx.params.get("speed", 2))
        except (TypeError, ValueError):
            raise ToolError("speed must be a number") from None
        speed = max(0.25, min(4.0, speed))
        if abs(speed - 1.0) < 1e-3:
            raise ToolError("pick a speed other than 1× (e.g. 2 to speed up, 0.5 for slow-mo)")

        src = ctx.input_paths[0]
        has_audio = probe(ctx, src)["audio"]
        out = ctx.output_dir / f"{src.stem}-{speed:g}x.mp4"

        if has_audio:
            fc = f"[0:v]setpts=PTS/{speed}[v];[0:a]{_atempo_chain(speed)}[a]"
            maps = ["-map", "[v]", "-map", "[a]", "-c:a", "aac"]
        else:
            fc = f"[0:v]setpts=PTS/{speed}[v]"
            maps = ["-map", "[v]"]

        ctx.progress(0.3, "changing speed")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
            "-filter_complex", fc, *maps,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-movflags", "+faststart", str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("speed change failed — the file may not be a valid video")
        guard_output_size(out, "video")
        ctx.progress(1.0, "done")
