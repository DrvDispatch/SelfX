"""Encode an MP4 within a verified upload budget."""

import math
import os
import shutil
import time
from typing import ClassVar

from ..config import settings
from ._media import LOCAL_INPUT_OPTIONS, max_output_bytes, probe
from .base import Tool, ToolContext, ToolError
from .registry import register

_MB = 1_000_000
_MIN_VIDEO_BITRATE = 24_000
_MAX_DURATION = 3600
_MAX_DIMENSION = 4096
_RESOLUTIONS = {"480p": (854, 480), "720p": (1280, 720), "1080p": (1920, 1080)}


def _fit_resolution(mode: str, bitrate: int) -> list[str]:
    if mode == "original":
        return ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"]
    if mode == "auto":
        if bitrate < 400_000:
            long, short = (640, 360)
        elif bitrate < 850_000:
            long, short = _RESOLUTIONS["480p"]
        elif bitrate < 1_800_000:
            long, short = _RESOLUTIONS["720p"]
        else:
            long, short = _RESOLUTIONS["1080p"]
    else:
        long, short = _RESOLUTIONS[mode]
    return [
        "-vf",
        (f"scale=w='min(iw,if(gte(iw,ih),{long},{short}))':"
         f"h='min(ih,if(gte(iw,ih),{short},{long}))':"
         "force_original_aspect_ratio=decrease:force_divisible_by=2"),
    ]


def _encode(ctx: ToolContext, args: list[str], deadline: float) -> None:
    remaining = int(deadline - time.monotonic())
    if remaining < 1:
        raise ToolError("Compression reached its time limit. Use a shorter clip or smaller resolution.")
    try:
        ctx.run_cmd(args, timeout=remaining)
    except ToolError as exc:
        if time.monotonic() >= deadline - 1:
            raise ToolError("Compression reached its time limit. Use a shorter clip or smaller resolution.") from None
        raise ToolError("FFmpeg could not encode this video as MP4. Check that it plays and try a smaller resolution.") from exc


@register
class VideoTargetSize(Tool):
    slug = "video-target-size"
    name = "Compress video to a size limit"
    category = "media"
    description = "Make an MP4 that fits an upload limit. Keeps the first audio track when selected."
    accepts: ClassVar[list[str]] = [".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".flv", ".wmv", ".mpg", ".mpeg"]
    queue = "heavy"
    params_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "target_mb": {
                "type": "number",
                "title": "Maximum file size (MB)",
                "description": "1 MB is 1,000,000 bytes. A smaller limit can reduce video resolution or detail.",
                "default": 25,
                "minimum": 0.1,
                "maximum": 1000,
            },
            "max_resolution": {
                "type": "string",
                "title": "Maximum resolution",
                "description": "Auto adjusts resolution to the size limit and keeps the source orientation.",
                "enum": ["auto", "480p", "720p", "1080p", "original"],
                "default": "auto",
            },
            "keep_audio": {
                "type": "boolean",
                "title": "Keep audio",
                "description": "Keep the first audio track. Turn off to make more room for the video.",
                "default": True,
            },
        },
        "additionalProperties": False,
    }

    def available(self) -> tuple[bool, str | None]:
        return (
            (True, None) if shutil.which("ffmpeg") and shutil.which("ffprobe")
            else (False, "Install FFmpeg and FFprobe to compress video")
        )

    def run(self, ctx: ToolContext) -> None:
        limit_mb = ctx.params.get("target_mb", 25)
        if type(limit_mb) not in (int, float) or not math.isfinite(limit_mb) or not 0.1 <= limit_mb <= 1000:
            raise ToolError("Enter a file size between 0.1 and 1000 MB")
        limit = int(limit_mb * _MB)
        if limit > max_output_bytes():
            raise ToolError("Choose a file size within the SelfX output limit")
        mode = ctx.params.get("max_resolution", "auto")
        if mode not in ("auto", "original", *_RESOLUTIONS):
            raise ToolError("Choose a supported resolution")

        source = ctx.input_paths[0].resolve()
        if source.stat().st_size > settings.max_upload_bytes:
            raise ToolError("This video exceeds the SelfX input size limit")
        info = probe(ctx, source, local_input=True, timeout=15)
        duration = info["duration"]
        video_duration = info["video_duration"] or duration
        if not info["video"] or not duration or not video_duration:
            raise ToolError("Choose a readable video with a known duration")
        if not math.isfinite(duration) or not math.isfinite(video_duration):
            raise ToolError("This video reports an invalid duration")
        duration = max(duration, video_duration)
        if not 0 < video_duration <= duration <= _MAX_DURATION:
            raise ToolError("Choose a video that is 60 minutes or shorter")
        if not all(2 <= (value or 0) <= _MAX_DIMENSION for value in (info["width"], info["height"])):
            raise ToolError("Choose a video with dimensions up to 4096 pixels")

        budget = int((limit * 0.94 - 12_288) * 8 / duration)
        with_audio = bool(ctx.params.get("keep_audio", True) and info["audio"])
        audio_bitrate = min(96_000, max(24_000, int(budget * 0.18))) if with_audio else 0
        bitrate = min(30_000_000, budget - audio_bitrate)
        if bitrate < _MIN_VIDEO_BITRATE:
            raise ToolError("The size limit is too small for this duration. Allow a larger file or trim the video.")
        if shutil.disk_usage(ctx.workdir).free < limit * 2 + 32 * _MB:
            raise ToolError("Free up disk space before compressing this video")

        pending = ctx.workdir.resolve() / "compressed.mp4"
        deadline = time.monotonic() + min(settings.job_timeout_seconds, 1200)
        # Used only as a disk safeguard. A candidate that reaches this cap
        # exceeds the user's limit and will never be published.
        write_cap = limit + max(128_000, limit // 8)
        for attempt in range(2):
            passlog = ctx.workdir.resolve() / f"size-pass-{attempt}"
            common = [
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                *LOCAL_INPUT_OPTIONS, "-threads", "2", "-i", str(source), "-map", "0:V:0",
                "-map_metadata", "-1", "-map_chapters", "-1", "-sn", "-dn",
                *_fit_resolution(mode, bitrate), "-filter_threads", "2",
                "-c:v", "libx264", "-preset", "veryfast", "-threads", "4", "-pix_fmt", "yuv420p",
                "-b:v", str(bitrate), "-passlogfile", str(passlog),
            ]
            ctx.progress(0.12 + 0.45 * attempt, "Analyzing video for the size limit")
            _encode(ctx, [*common, "-pass", "1", "-an", "-f", "null", os.devnull], deadline)
            audio = ["-map", "0:a:0", "-c:a", "aac", "-ac", "2", "-b:a", str(audio_bitrate)] if with_audio else ["-an"]
            ctx.progress(0.34 + 0.45 * attempt, "Encoding MP4")
            _encode(ctx, [*common, "-pass", "2", *audio, "-fs", str(write_cap),
                          "-movflags", "+faststart", "-f", "mp4", str(pending)], deadline)
            if not pending.is_file() or pending.stat().st_size == 0:
                raise ToolError("Compression did not produce a video")
            size = pending.stat().st_size
            if size <= limit:
                output = probe(ctx, pending, local_input=True, timeout=15)
                output_duration = output["video_duration"] or output["duration"] or 0
                tolerance = max(0.25, min(1.0, video_duration * 0.01))
                if (not output["video"] or output["audio"] != with_audio
                        or not math.isfinite(output_duration) or output_duration < video_duration - tolerance):
                    raise ToolError("The compressed MP4 did not contain the complete video. Try a larger file limit.")
                pending.replace(ctx.output_dir / f"{source.stem}-compressed.mp4")
                ctx.progress(1, f"Saved {size / _MB:.2f} MB (limit {limit_mb:g} MB)")
                return
            bitrate = int(bitrate * min(0.85, 0.94 * limit / size))
            if bitrate < _MIN_VIDEO_BITRATE:
                break
        raise ToolError("The video could not fit this size limit. Allow a larger file or trim the video.")
