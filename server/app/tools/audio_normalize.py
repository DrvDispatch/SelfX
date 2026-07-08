"""audio-normalize: even out loudness with FFmpeg's EBU R128 loudnorm filter."""

import json

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
    params_schema = {
        "type": "object",
        "properties": {
            "target_lufs": {
                "type": "number",
                "title": "Target loudness (LUFS)",
                "description": "Integrated loudness target. -16 for general use, "
                               "-14 for streaming/podcasts, -23 for EBU broadcast.",
                "minimum": -40,
                "maximum": -5,
                "default": -16,
            },
            "true_peak": {
                "type": "number",
                "title": "Max true peak (dBTP)",
                "description": "Ceiling for the loudest peak. -1.5 is a safe default.",
                "minimum": -9,
                "maximum": 0,
                "default": -1.5,
            },
            "lra": {
                "type": "number",
                "title": "Loudness range (LRA)",
                "description": "Target loudness range. Higher keeps more dynamics.",
                "minimum": 1,
                "maximum": 50,
                "default": 11,
            },
            "two_pass": {
                "type": "boolean",
                "title": "Two-pass (accurate)",
                "description": "Measure the file first, then normalize with those "
                               "measurements for far more accurate loudness and a "
                               "reliable peak ceiling. Roughly doubles processing time.",
                "default": False,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        ext = src.suffix.lower().lstrip(".") or "mp3"
        out = ctx.output_dir / f"{src.stem}-normalized.{ext}"

        info = probe(ctx, src)
        probe_worked = info["video"] or info["audio"] or info["duration"] is not None
        if probe_worked and not info["audio"]:
            raise ToolError("this file has no audio track to normalize")

        target_i = self._clamp(ctx.params.get("target_lufs"), -40, -5, -16.0)
        target_tp = self._clamp(ctx.params.get("true_peak"), -9, 0, -1.5)
        target_lra = self._clamp(ctx.params.get("lra"), 1, 50, 11.0)
        base = f"I={target_i}:TP={target_tp}:LRA={target_lra}"

        # loudnorm internally resamples to 192 kHz; pin the output rate back to the
        # source (default 48k) so a 44.1 kHz mp3 doesn't balloon into a 192 kHz file.
        out_sr = info.get("asample_rate") or 48000
        extra = ["-ar", str(out_sr)]
        if ext in _LOSSY_BITS:
            # carry the source bitrate instead of the ~128k encoder default.
            extra += ["-b:a", audio_bitrate_arg(info, _LOSSY_BITS[ext])]

        af = f"loudnorm={base}"
        if bool(ctx.params.get("two_pass", False)):
            measured = self._measure(ctx, src, base)
            if measured:
                af = f"loudnorm={base}:{measured}:linear=true"

        ctx.progress(0.5, "normalizing loudness")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
            "-af", af, *extra, str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("normalization failed — the input may not contain audio")
        ctx.progress(1.0, "done")

    def _measure(self, ctx: ToolContext, src, base: str) -> str | None:
        """Run the loudnorm analysis pass and return `measured_*`/`offset` params.

        Returns None (falling back to single-pass) if the measurement can't be
        parsed, so two-pass never turns a working job into a failure.
        """
        ctx.progress(0.25, "measuring loudness (pass 1 of 2)")
        try:
            proc = ctx.run_cmd([
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
                "-af", f"loudnorm={base}:print_format=json", "-f", "null", "-",
            ])
        except ToolError:
            return None
        stderr = proc.stderr or ""
        start = stderr.rfind("{")
        end = stderr.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(stderr[start:end + 1])
        except (ValueError, TypeError):
            return None
        try:
            return (
                f"measured_I={float(data['input_i'])}"
                f":measured_TP={float(data['input_tp'])}"
                f":measured_LRA={float(data['input_lra'])}"
                f":measured_thresh={float(data['input_thresh'])}"
                f":offset={float(data['target_offset'])}"
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _clamp(value, lo: float, hi: float, default: float) -> float:
        try:
            if value is None or value == "":
                return default
            return max(lo, min(hi, float(value)))
        except (TypeError, ValueError):
            return default
