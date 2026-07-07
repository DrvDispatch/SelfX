"""subtitle-convert: convert between subtitle formats (SRT / VTT / ASS) with FFmpeg."""

import shutil

from ._subtitles import (
    looks_like_text_subtitle,
    normalize_to_utf8,
    validate_has_cues,
)
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
            },
            "encoding": {
                "type": "string",
                "title": "Input encoding",
                "description": "Override the detected input charset (e.g. cp1256, cp1251, gbk). Leave blank to auto-detect.",
                "default": "",
                "maxLength": 32,
            },
        },
        "required": ["to"],
    }

    def available(self) -> tuple[bool, str | None]:
        if shutil.which("ffmpeg"):
            return True, None
        return False, "the subtitle engine (FFmpeg) is not installed"

    def run(self, ctx: ToolContext) -> None:
        to = str(ctx.params.get("to", "vtt"))
        if to not in ("srt", "vtt", "ass"):
            raise ToolError(f"unsupported target format '{to}'")
        src = ctx.input_paths[0]
        if src.suffix.lower().lstrip(".") == to:
            raise ToolError(f"the file is already in {to} format")
        if not looks_like_text_subtitle(src):
            raise ToolError("this doesn't look like a subtitle file (it appears to be binary)")

        # Non-UTF-8 subs (CP1256/CP1251/GBK/Big5/Shift-JIS/Latin-1/UTF-16) are the
        # #1 real-world failure: ffmpeg would abort on "Invalid UTF-8" or mojibake.
        # Normalize to clean UTF-8 first (respecting an optional manual override).
        override = str(ctx.params.get("encoding", "") or "").strip() or None
        source = normalize_to_utf8(src, ctx.workdir, override=override)

        out = ctx.output_dir / f"{src.stem}.{to}"
        ctx.progress(0.4, f"converting to {to}")
        try:
            ctx.run_cmd([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", str(source), str(out),
            ])
        except ToolError:
            raise ToolError(
                "conversion failed — this doesn't look like a valid subtitle file"
            ) from None
        # Validate SEMANTIC output: >= 1 real cue, not just > 0 bytes (a zero-cue
        # source becomes a useless header-only 'WEBVTT\n\n' otherwise).
        validate_has_cues(out)
        ctx.progress(1.0, "done")
