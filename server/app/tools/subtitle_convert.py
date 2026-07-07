"""subtitle-convert: convert between subtitle formats (SRT / VTT / ASS) with FFmpeg."""

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class SubtitleConvert(Tool):
    slug = "subtitle-convert"
    name = "Convert subtitles"
    category = "subtitles"
    description = "Convert a subtitle file between SubRip (.srt), WebVTT (.vtt) and ASS (.ass)."
    accepts = [".srt", ".vtt", ".ass", ".ssa"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "title": "Convert to",
                "enum": ["srt", "vtt", "ass"],
                "default": "vtt",
            }
        },
        "required": ["to"],
    }

    def run(self, ctx: ToolContext) -> None:
        to = str(ctx.params.get("to", "vtt"))
        if to not in ("srt", "vtt", "ass"):
            raise ToolError(f"unsupported target format '{to}'")
        src = ctx.input_paths[0]
        if src.suffix.lower().lstrip(".") == to:
            raise ToolError(f"the file is already in {to} format")
        out = ctx.output_dir / f"{src.stem}.{to}"
        ctx.progress(0.4, f"converting to {to}")
        ctx.run_cmd(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src), str(out)])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("conversion failed — the subtitle file may be malformed")
        ctx.progress(1.0, "done")
