"""subtitle-extract: pull an embedded subtitle track out of a video into a .srt file."""

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class SubtitleExtract(Tool):
    slug = "subtitle-extract"
    name = "Extract subtitles"
    category = "subtitles"
    description = "Extract an embedded subtitle track from a video (e.g. .mkv) as a .srt file."
    accepts = [".mkv", ".mp4", ".mov", ".webm", ".avi", ".m4v", ".ts"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "track": {
                "type": "integer",
                "title": "Track number",
                "description": "Which subtitle track (0 = first)",
                "minimum": 0,
                "maximum": 30,
                "default": 0,
            }
        },
    }

    def run(self, ctx: ToolContext) -> None:
        track = int(ctx.params.get("track", 0))
        src = ctx.input_paths[0]
        out = ctx.output_dir / f"{src.stem}.srt"
        ctx.progress(0.4, "extracting subtitles")
        try:
            ctx.run_cmd([
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
                "-map", f"0:s:{track}", str(out),
            ])
        except ToolError:
            raise ToolError(
                "no embedded subtitle track found at that index — this video may have no subtitles"
            ) from None
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("no subtitles were extracted")
        ctx.progress(1.0, "done")
