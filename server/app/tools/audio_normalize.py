"""audio-normalize: even out loudness with FFmpeg's EBU R128 loudnorm filter."""

from .base import Tool, ToolContext, ToolError
from .registry import register


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
        ctx.progress(0.3, "normalizing loudness")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("normalization failed — the input may not contain audio")
        ctx.progress(1.0, "done")
