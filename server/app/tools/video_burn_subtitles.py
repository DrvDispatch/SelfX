"""video-burn-subtitles: hardcode a subtitle file into the video picture (FFmpeg + libass)."""

import shutil

from ._media import guard_output_size
from .base import Tool, ToolContext, ToolError
from .registry import register

_VIDEO = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg"]
_SUBS = [".srt", ".vtt", ".ass", ".ssa"]
# BGR hex for libass PrimaryColour (&HAABBGGRR, AA=00 opaque)
_COLOR = {"white": "&H00FFFFFF", "yellow": "&H0000FFFF", "black": "&H00000000"}
_ALIGN = {"bottom": 2, "top": 8}


@register
class VideoBurnSubtitles(Tool):
    slug = "video-burn-subtitles"
    name = "Burn in subtitles"
    category = "media"
    description = "Permanently render a subtitle file (.srt/.vtt/.ass) into the video picture. Attach the video and the subtitles."
    accepts = _VIDEO + _SUBS
    multi_file = True
    min_files = 2
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "font_size": {"type": "integer", "title": "Font size", "minimum": 8, "maximum": 96, "default": 24},
            "color": {"type": "string", "title": "Text colour", "enum": ["white", "yellow", "black"], "default": "white"},
            "position": {"type": "string", "title": "Position", "enum": ["bottom", "top"], "default": "bottom"},
        },
    }

    def run(self, ctx: ToolContext) -> None:
        video = next((p for p in ctx.input_paths if p.suffix.lower() in _VIDEO), None)
        sub = next((p for p in ctx.input_paths if p.suffix.lower() in _SUBS), None)
        if video is None or sub is None:
            raise ToolError("attach one video and one subtitle file (.srt / .vtt / .ass)")

        # Copy the subtitle to a plain name in the workdir so the filter path needs no
        # escaping (run_cmd runs with cwd=workdir).
        local = f"subs{sub.suffix.lower()}"
        shutil.copy2(sub, ctx.workdir / local)

        if sub.suffix.lower() in (".ass", ".ssa"):
            vf = f"ass={local}"  # keeps the file's own styling
        else:
            size = int(ctx.params.get("font_size", 24))
            color = _COLOR.get(str(ctx.params.get("color", "white")), _COLOR["white"])
            align = _ALIGN.get(str(ctx.params.get("position", "bottom")), 2)
            style = f"FontSize={size},PrimaryColour={color},Outline=1,Shadow=0,Alignment={align}"
            vf = f"subtitles={local}:force_style='{style}'"

        out = ctx.output_dir / f"{video.stem}-subtitled.mp4"
        ctx.progress(0.3, "burning in subtitles")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(video),
            "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-movflags", "+faststart", str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("burning in subtitles failed — check the subtitle file is valid")
        guard_output_size(out, "subtitled video")
        ctx.progress(1.0, "done")
