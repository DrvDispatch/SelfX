"""audio-extract: pull the audio track out of a video (or transcode audio) with FFmpeg."""

from .base import Tool, ToolContext, ToolError
from .registry import register

_CODEC = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "aac": ["-c:a", "aac", "-b:a", "192k"],
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
}


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
        ctx.progress(0.3, "extracting audio")
        ctx.run_cmd(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src), "-vn", *codec, str(out)])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("no audio track found or extraction failed")
        ctx.progress(1.0, "done")
