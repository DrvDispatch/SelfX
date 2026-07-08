"""video-thumbnail: grab a single frame from a video as an image."""

from ._media import probe, validate_time
from .base import Tool, ToolContext, ToolError
from .registry import register

_FORMATS = {"jpg": "jpg", "png": "png", "webp": "webp"}


@register
class VideoThumbnail(Tool):
    slug = "video-thumbnail"
    name = "Video thumbnail"
    category = "media"
    description = "Capture a single frame from a video at a chosen time as an image (JPEG, PNG or WebP)."
    accepts = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "time": {
                "type": "string",
                "title": "Timestamp",
                "description": "When to grab the frame: seconds, HH:MM:SS, or a "
                               "percentage of the duration (e.g. 50%).",
                "default": "00:00:01",
                "maxLength": 12,
            },
            "format": {
                "type": "string",
                "title": "Image format",
                "enum": ["jpg", "png", "webp"],
                "default": "jpg",
            },
            "width": {
                "type": "integer",
                "title": "Max width (px)",
                "description": "Optionally cap the output width so a 4K frame isn't huge.",
                "minimum": 16,
                "maximum": 7680,
            },
            "quality": {
                "type": "integer",
                "title": "Quality",
                "description": "JPEG: 2 (best) to 31. WebP: 0 to 100 (higher better). "
                               "Ignored for PNG (lossless).",
                "minimum": 0,
                "maximum": 100,
            },
            "precise": {
                "type": "boolean",
                "title": "Frame-exact seek",
                "description": "Decode to the exact timestamp (slower) instead of the "
                               "nearest keyframe (fast).",
                "default": False,
            },
            "smart": {
                "type": "boolean",
                "title": "Pick a representative frame",
                "description": "Choose the most representative frame near the timestamp "
                               "(avoids black/blurry frames) — good for poster images.",
                "default": False,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        fmt = str(ctx.params.get("format", "jpg"))
        if fmt not in _FORMATS:
            fmt = "jpg"
        out = ctx.output_dir / f"{src.stem}-thumb.{fmt}"

        time = self._resolve_time(ctx, src)
        precise = bool(ctx.params.get("precise", False))
        smart = bool(ctx.params.get("smart", False))

        filters = []
        if smart:
            # Scan ~2s of frames and keep the most representative one.
            filters.append("thumbnail=60")
        width = ctx.params.get("width")
        if width not in (None, ""):
            # -2 keeps the aspect ratio while forcing an even height for the encoder.
            filters.append(f"scale={int(width)}:-2")
        vf = ["-vf", ",".join(filters)] if filters else []

        # Fast seek (-ss before -i) unless the user wants a frame-exact grab.
        seek_in = [] if precise else ["-ss", time]
        seek_out = ["-ss", time] if precise else []

        ctx.progress(0.4, "capturing frame")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y",
            *seek_in, "-i", str(src), *seek_out,
            "-frames:v", "1", "-an", "-sn",
            *vf, *self._quality_args(fmt, ctx.params.get("quality")), str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("could not capture a frame — the timestamp may be past the end")
        ctx.progress(1.0, "done")

    def _resolve_time(self, ctx: ToolContext, src) -> str:
        """Return an ffmpeg -ss value, resolving a `NN%` timestamp against the duration."""
        raw = str(ctx.params.get("time", "00:00:01") or "00:00:01").strip()
        if raw.endswith("%"):
            try:
                pct = max(0.0, min(100.0, float(raw[:-1].strip())))
            except ValueError:
                raise ToolError(f"'{raw}' is not a valid percentage timestamp") from None
            duration = probe(ctx, src).get("duration")
            if not duration or duration <= 0:
                raise ToolError(
                    "couldn't read the video length to resolve a percentage — "
                    "use a time like 00:01:30 instead"
                )
            return f"{duration * pct / 100:.3f}"
        return validate_time(raw, "timestamp")

    @staticmethod
    def _quality_args(fmt: str, quality) -> list[str]:
        try:
            q = None if quality in (None, "") else int(quality)
        except (TypeError, ValueError):
            q = None
        if fmt == "jpg":
            val = 2 if q is None else max(2, min(31, q))
            return ["-q:v", str(val)]
        if fmt == "webp":
            val = 90 if q is None else max(0, min(100, q))
            return ["-quality", str(val)]
        return []  # png: lossless, no quality knob
