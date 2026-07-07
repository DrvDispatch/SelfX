"""audio-normalize: even out loudness with FFmpeg's EBU R128 loudnorm filter."""

from ._media import audio_bitrate_arg, probe
from .base import Tool, ToolContext, ToolError
from .registry import register

# lossy output formats -> encoder + fallback bitrate. loudnorm otherwise re-encodes
# with ffmpeg's ~128k default, silently downgrading a 320k source.
_LOSSY_BITS = {"mp3": 192000, "aac": 192000, "m4a": 192000,
               "ogg": 160000, "opus": 128000, "wma": 128000}


@register
class AudioNormalize(Tool):
    slug = "audio-normalize"
    name = "Normalize audio"
    category = "media"
    description = "Normalize perceived loudness to a broadcast standard (EBU R128) so volume is consistent."
    accepts = [".mp3", ".wav", ".flac", ".aac", ".ogg", ".opus", ".m4a", ".wma", ".aiff"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {"type": "object", "properties": {}}

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        ext = src.suffix.lower().lstrip(".") or "mp3"
        out = ctx.output_dir / f"{src.stem}-normalized.{ext}"

        info = probe(ctx, src)
        probe_worked = info["video"] or info["audio"] or info["duration"] is not None
        if probe_worked and not info["audio"]:
            raise ToolError("this file has no audio track to normalize")

        # loudnorm internally resamples to 192 kHz; pin the output rate back to the
        # source (default 48k) so a 44.1 kHz mp3 doesn't balloon into a 192 kHz file.
        out_sr = info.get("asample_rate") or 48000
        extra = ["-ar", str(out_sr)]
        if ext in _LOSSY_BITS:
            # carry the source bitrate instead of the ~128k encoder default.
            extra += ["-b:a", audio_bitrate_arg(info, _LOSSY_BITS[ext])]

        ctx.progress(0.3, "normalizing loudness")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", *extra, str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("normalization failed — the input may not contain audio")
        ctx.progress(1.0, "done")
