"""subtitle-extract: pull an embedded subtitle track out of a video into a .srt file."""

import json
import shutil

from ._subtitles import IMAGE_SUB_CODECS, validate_has_cues
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
                "description": "Which subtitle track (0 = first). Ignored when a language is given.",
                "minimum": 0,
                "maximum": 30,
                "default": 0,
            },
            "language": {
                "type": "string",
                "title": "Language",
                "description": "Pick the track by language tag (e.g. eng, ara, ger). Leave blank to use the track number.",
                "default": "",
                "maxLength": 12,
            },
            "format": {
                "type": "string",
                "title": "Output format",
                "description": "Text subtitle format to write. ASS preserves styling when the source track is ASS.",
                "enum": ["srt", "ass", "vtt"],
                "default": "srt",
            },
        },
    }

    def available(self) -> tuple[bool, str | None]:
        if shutil.which("ffmpeg") and shutil.which("ffprobe"):
            return True, None
        return False, "the subtitle engine (FFmpeg) is not installed"

    def _probe_streams(self, ctx: ToolContext, src) -> list[dict] | None:
        """Return the list of subtitle streams via ffprobe, or None if unknown."""
        try:
            proc = ctx.run_cmd([
                "ffprobe", "-v", "error", "-select_streams", "s",
                "-show_entries", "stream=index,codec_name,codec_type:stream_tags=language,title",
                "-of", "json", str(src),
            ])
            data = json.loads(proc.stdout or "{}")
            streams = data.get("streams")
            return streams if isinstance(streams, list) else None
        except Exception:
            # ffprobe missing/odd output: don't block — fall through to ffmpeg.
            return None

    def run(self, ctx: ToolContext) -> None:
        track = int(ctx.params.get("track", 0))
        language = str(ctx.params.get("language", "") or "").strip().lower()
        fmt = str(ctx.params.get("format", "srt") or "srt").strip().lower()
        if fmt not in ("srt", "ass", "vtt"):
            fmt = "srt"
        src = ctx.input_paths[0]
        out = ctx.output_dir / f"{src.stem}.{fmt}"
        ctx.progress(0.3, "inspecting subtitle tracks")

        # Probe first so we can give an ACCURATE, actionable error instead of the
        # old catch-all "no embedded subtitle track found" for every failure mode.
        streams = self._probe_streams(ctx, src)
        if streams is not None:
            n = len(streams)
            if n == 0:
                raise ToolError("no subtitle tracks were found in this video")
            # Language selection overrides the track index when requested. The
            # position within the subtitle-only stream list IS the -map 0:s:N index.
            if language:
                match = None
                for i, s in enumerate(streams):
                    tags = s.get("tags") or {}
                    lang = str(tags.get("language", "")).lower()
                    if lang == language:
                        match = i
                        break
                if match is None:
                    avail = ", ".join(
                        str((s.get("tags") or {}).get("language", "und")) for s in streams
                    )
                    raise ToolError(
                        f"no subtitle track tagged language '{language}' — "
                        f"available: {avail}"
                    )
                track = match
            if track >= n:
                raise ToolError(
                    f"track {track} does not exist — this video has "
                    f"{n} subtitle track(s) (valid indexes 0..{n - 1})"
                )
            codec = str(streams[track].get("codec_name", "")).lower()
            if codec in IMAGE_SUB_CODECS:
                raise ToolError(
                    f"subtitle track {track} is image-based ({codec}, e.g. PGS/VobSub/DVB) — "
                    "it can't be extracted as text and would need OCR"
                )

        ctx.progress(0.5, "extracting subtitles")
        try:
            ctx.run_cmd([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", str(src), "-map", f"0:s:{track}", str(out),
            ])
        except ToolError:
            # If probing already validated the track, this is a real decode/mux
            # failure rather than an absent track.
            raise ToolError(
                f"could not extract subtitle track {track} — the track may be "
                "corrupt or image-based (needs OCR)"
            ) from None
        # Validate SEMANTIC output: >= 1 real cue, not just > 0 bytes.
        validate_has_cues(out)
        ctx.progress(1.0, "done")
