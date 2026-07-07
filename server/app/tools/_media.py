"""Shared helpers for the media/audio/video tools.

Centralises ffprobe stream inspection, a time-string validator, source-bitrate
carry-over, and an output-size guard so the ffmpeg-backed tools stay surgical and
consistent. Everything here is best-effort: probing failures degrade to "unknown"
rather than blocking a job, so happy-path behaviour is preserved.
"""

import json
import re

from ..config import settings
from .base import ToolContext, ToolError

# Codecs that show up as a "video" stream but are really attached cover art
# (album art in an mp3/flac, a poster in an m4a). They must NOT count as a real
# video track when deciding whether a video preset is applicable.
_COVER_ART_CODECS = {"mjpeg", "png", "bmp", "gif", "jpeg", "tiff", "webp"}

_TIME_RE = re.compile(r"^(?:\d+(?:\.\d+)?|\d{1,3}(?::[0-5]?\d){1,2}(?:\.\d+)?)$")


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def max_output_bytes() -> int:
    """Per-job output ceiling (defaults to 1024 MB if the setting is absent)."""
    mb = getattr(settings, "max_output_mb", 1024)
    try:
        return max(1, int(mb)) * 1024 * 1024
    except (TypeError, ValueError):
        return 1024 * 1024 * 1024


def probe(ctx: ToolContext, src) -> dict:
    """Inspect a media file with a single ffprobe call.

    Returns a dict with keys: video (bool), audio (bool), vcodec, acodec,
    abitrate (bits/s), asample_rate, width, height, duration (seconds). Missing
    or unreadable values come back as None/False — never raises.
    """
    info = {
        "video": False, "audio": False, "vcodec": None, "acodec": None,
        "abitrate": None, "asample_rate": None, "width": None, "height": None,
        "duration": None,
    }
    try:
        proc = ctx.run_cmd(
            ["ffprobe", "-v", "error",
             "-show_entries",
             "stream=codec_type,codec_name,bit_rate,sample_rate,width,height:format=duration",
             "-of", "json", str(src)],
            timeout=60,
        )
        data = json.loads(proc.stdout or "{}")
    except (ToolError, ValueError, TypeError):
        return info

    for stream in data.get("streams", []):
        ctype = stream.get("codec_type")
        cname = stream.get("codec_name")
        if ctype == "video":
            if cname in _COVER_ART_CODECS:
                continue  # attached picture, not a real video track
            if not info["video"]:
                info["video"] = True
                info["vcodec"] = cname
                info["width"] = _to_int(stream.get("width"))
                info["height"] = _to_int(stream.get("height"))
        elif ctype == "audio":
            if not info["audio"]:
                info["audio"] = True
                info["acodec"] = cname
                info["abitrate"] = _to_int(stream.get("bit_rate"))
                info["asample_rate"] = _to_int(stream.get("sample_rate"))
    info["duration"] = _to_float((data.get("format") or {}).get("duration"))
    return info


def validate_time(value: str, field: str = "start") -> str:
    """Validate an ffmpeg -ss/-t time string: plain seconds or [HH:]MM:SS[.ms].

    Returns the cleaned value or raises ToolError with a precise message instead
    of letting a nonsense value fail deep inside ffmpeg.
    """
    cleaned = str(value).strip()
    if not cleaned:
        return "0"
    if not _TIME_RE.match(cleaned):
        raise ToolError(
            f"'{cleaned}' is not a valid {field} time — use seconds (e.g. 12 or 12.5) "
            "or HH:MM:SS (e.g. 00:01:30)"
        )
    return cleaned


def audio_bitrate_arg(info: dict, default_bits: int, cap_bits: int = 320000) -> str:
    """Pick an -b:a value that carries the source bitrate instead of a fixed default.

    Falls back to default_bits when the source bitrate is unknown, and never
    exceeds cap_bits so a mislabelled stream can't request an absurd bitrate.
    """
    src_bits = info.get("abitrate")
    if isinstance(src_bits, int) and src_bits > 0:
        return str(min(src_bits, cap_bits))
    return str(default_bits)


def guard_output_size(path, label: str = "output") -> None:
    """Delete and reject an output that exceeds the per-job size ceiling."""
    try:
        size = path.stat().st_size
    except OSError:
        return
    cap = max_output_bytes()
    if size > cap:
        try:
            path.unlink()
        except OSError:
            pass
        raise ToolError(
            f"the {label} is larger than the {cap // (1024 * 1024)} MB limit — "
            "use a shorter clip, lower quality, or a smaller size"
        )
