"""audio-extract: pull the audio track out of a video (or transcode audio) with FFmpeg."""

from ._media import audio_bitrate_arg, probe
from .base import Tool, ToolContext, ToolError
from .registry import register

_CODEC = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "aac": ["-c:a", "aac", "-b:a", "192k"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
}

# format -> source codec_name that lets us stream-copy instead of re-encoding.
# m4a is an mp4 container, so an AAC source drops straight in without a transcode.
_COPYABLE = {"mp3": "mp3", "aac": "aac", "m4a": "aac", "flac": "flac",
             "opus": "opus", "wav": "pcm_s16le"}

# Linear-PCM source codecs we can stream-copy into a WAV container losslessly.
# Without this, a 24-bit / float master would be silently truncated to 16-bit.
_WAV_COPY_PCM = {"pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le",
                 "pcm_u8", "pcm_s16be", "pcm_s24be", "pcm_s32be"}

# lossy formats whose default bitrate we replace with the carried source bitrate.
_LOSSY_DEFAULT_BITS = {"aac": 192000, "m4a": 192000, "opus": 128000}

# formats where an explicit -b:a bitrate is meaningful (lossy encoders).
_LOSSY = {"mp3", "aac", "m4a", "opus"}


@register
class AudioExtract(Tool):
    slug = "audio-extract"
    name = "Extract audio"
    category = "media"
    description = "Extract (or convert) the audio track of a video/audio file to mp3, aac, m4a, wav, flac or opus."
    accepts = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv",
               ".mp3", ".wav", ".flac", ".aac", ".ogg", ".opus", ".m4a"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "title": "Audio format",
                "enum": ["mp3", "aac", "m4a", "wav", "flac", "opus"],
                "default": "mp3",
            },
            "bitrate": {
                "type": "integer",
                "title": "Bitrate (kbps)",
                "description": "Target bitrate for lossy formats (mp3/aac/m4a/opus). "
                               "Leave blank for the smart default.",
                "minimum": 32,
                "maximum": 512,
            },
            "sample_rate": {
                "type": "integer",
                "title": "Sample rate (Hz)",
                "description": "Optionally resample (e.g. 44100 or 48000).",
                "enum": [8000, 16000, 22050, 32000, 44100, 48000, 96000],
            },
            "channels": {
                "type": "integer",
                "title": "Channels",
                "description": "1 = mono, 2 = stereo. Leave blank to keep the source layout.",
                "minimum": 1,
                "maximum": 8,
            },
        },
        "required": ["format"],
    }

    def run(self, ctx: ToolContext) -> None:
        fmt = str(ctx.params.get("format", "mp3"))
        codec = _CODEC.get(fmt)
        if codec is None:
            raise ToolError(f"unsupported audio format '{fmt}'")
        src = ctx.input_paths[0]
        out = ctx.output_dir / f"{src.stem}.{fmt}"

        info = probe(ctx, src)
        # Only trust "no audio" when the probe clearly worked (found video/duration),
        # so a probe failure never falsely rejects a real audio file.
        probe_worked = info["video"] or info["audio"] or info["duration"] is not None
        if probe_worked and not info["audio"]:
            raise ToolError("this file has no audio track to extract")

        # Optional resample / re-channel / bitrate overrides. Any of these forces a
        # re-encode (you can't stream-copy while changing the audio parameters).
        extra: list[str] = []
        sample_rate = self._clamp_int(ctx.params.get("sample_rate"), 8000, 192000)
        if sample_rate is not None:
            extra += ["-ar", str(sample_rate)]
        channels = self._clamp_int(ctx.params.get("channels"), 1, 8)
        if channels is not None:
            extra += ["-ac", str(channels)]
        bitrate = self._clamp_int(ctx.params.get("bitrate"), 32, 512)
        force_encode = bool(extra) or (bitrate is not None and fmt in _LOSSY)

        acodec = info.get("acodec")
        can_copy = (
            (fmt == "wav" and acodec in _WAV_COPY_PCM)
            or acodec == _COPYABLE.get(fmt)
        )
        if can_copy and not force_encode:
            # source codec already fits the target container: copy, don't re-encode.
            codec = ["-c:a", "copy"]
            ctx.progress(0.3, "copying audio (no re-encode)")
        else:
            codec = list(codec)
            if bitrate is not None and fmt in _LOSSY:
                # explicit user bitrate: drop the format's VBR/CBR default and set it.
                self._set_bitrate(codec, f"{bitrate}k")
            elif fmt in _LOSSY_DEFAULT_BITS and "-b:a" in codec:
                # carry the source bitrate instead of the fixed default downgrade.
                codec[codec.index("-b:a") + 1] = audio_bitrate_arg(
                    info, _LOSSY_DEFAULT_BITS[fmt]
                )
            ctx.progress(0.3, "extracting audio")

        ctx.run_cmd(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
                     "-vn", *codec, *extra, str(out)])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("extraction failed — the input may have no audio track or be corrupt")
        ctx.progress(1.0, "done")

    @staticmethod
    def _clamp_int(value, lo: int, hi: int) -> int | None:
        try:
            if value is None or value == "":
                return None
            return max(lo, min(hi, int(value)))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _set_bitrate(codec: list[str], value: str) -> None:
        """Force -b:a to `value`, replacing any VBR (-q:a) or existing bitrate flag."""
        for flag in ("-q:a", "-b:a"):
            if flag in codec:
                idx = codec.index(flag)
                del codec[idx:idx + 2]
        codec += ["-b:a", value]
