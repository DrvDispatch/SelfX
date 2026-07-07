"""audio-extract: pull the audio track out of a video (or transcode audio) with FFmpeg."""

from ._media import audio_bitrate_arg, probe
from .base import Tool, ToolContext, ToolError
from .registry import register

_CODEC = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "aac": ["-c:a", "aac", "-b:a", "192k"],
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
}

# format -> source codec_name that lets us stream-copy instead of re-encoding.
_COPYABLE = {"mp3": "mp3", "aac": "aac", "flac": "flac",
             "opus": "opus", "wav": "pcm_s16le"}

# lossy formats whose default bitrate we replace with the carried source bitrate.
_LOSSY_DEFAULT_BITS = {"aac": 192000, "opus": 128000}


@register
class AudioExtract(Tool):
    slug = "audio-extract"
    name = "Extract audio"
    category = "media"
    description = "Extract (or convert) the audio track of a video/audio file to mp3, aac, wav, flac or opus."
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
                "enum": ["mp3", "aac", "wav", "flac", "opus"],
                "default": "mp3",
            }
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

        if info.get("acodec") == _COPYABLE.get(fmt):
            # source codec already matches the target container: copy, don't re-encode.
            codec = ["-c:a", "copy"]
            ctx.progress(0.3, "copying audio (no re-encode)")
        else:
            codec = list(codec)
            if fmt in _LOSSY_DEFAULT_BITS and "-b:a" in codec:
                # carry the source bitrate instead of the fixed default downgrade.
                codec[codec.index("-b:a") + 1] = audio_bitrate_arg(
                    info, _LOSSY_DEFAULT_BITS[fmt]
                )
            ctx.progress(0.3, "extracting audio")

        ctx.run_cmd(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
                     "-vn", *codec, str(out)])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("extraction failed — the input may have no audio track or be corrupt")
        ctx.progress(1.0, "done")
