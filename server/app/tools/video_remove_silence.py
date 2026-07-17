"""video-remove-silence: auto-cut the silent / quiet parts out of a video (auto-editor)."""

import sys

from ._media import guard_output_size
from .base import Tool, ToolContext, ToolError
from .registry import register

_VIDEO = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg"]


@register
class VideoRemoveSilence(Tool):
    slug = "video-remove-silence"
    name = "Remove silence (auto-cut)"
    category = "media"
    description = "Automatically cut out the silent/quiet gaps in a video — great for tightening talking-head clips."
    accepts = _VIDEO
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "threshold": {
                "type": "integer",
                "title": "Loudness threshold (%)",
                "description": "Audio below this % of full volume counts as silence. Higher cuts more.",
                "minimum": 1,
                "maximum": 50,
                "default": 4,
            },
            "margin": {
                "type": "number",
                "title": "Keep padding (seconds)",
                "description": "Padding kept around each kept segment so cuts don't feel abrupt.",
                "minimum": 0,
                "maximum": 2,
                "default": 0.2,
            },
        },
    }

    def available(self) -> tuple[bool, str | None]:
        try:
            import auto_editor  # noqa: F401
            return True, None
        except Exception:
            return False, "the auto-cut engine (auto-editor) is not installed"

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        threshold = max(1, min(50, int(ctx.params.get("threshold", 4))))
        try:
            margin = max(0.0, min(2.0, float(ctx.params.get("margin", 0.2))))
        except (TypeError, ValueError):
            margin = 0.2

        out = ctx.output_dir / f"{src.stem}-cut.mp4"
        ctx.progress(0.25, "analysing audio and cutting (this can take a while)")
        try:
            ctx.run_cmd([
                sys.executable, "-m", "auto_editor", str(src),
                "--edit", f"audio:threshold={threshold}%",
                "--margin", f"{margin}sec",
                "--no-open", "-o", str(out),
            ])
        except ToolError as exc:
            msg = str(exc).lower()
            if "no active" in msg or "empty" in msg or "0 clip" in msg:
                raise ToolError("nothing was loud enough to keep — lower the threshold") from None
            raise ToolError("auto-cut failed — the file may have no audio or be unsupported") from None
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("auto-cut produced no output — try a lower threshold")
        guard_output_size(out, "cut video")
        ctx.progress(1.0, "done")
