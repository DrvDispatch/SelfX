"""Normalize the order, text, and timecodes of SRT and WebVTT cues."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from ._media import guard_output_size
from ._subtitles import detect_encoding
from .base import Tool, ToolContext, ToolError
from .registry import register

_MAX_SUBTITLE_BYTES = 8 * 1024 * 1024
_MAX_CUES = 50_000
_BLOCKS = re.compile(r"\n(?:[ \t]*\n)+")
_STAMP = r"(?:[0-9]{1,5}:)?[0-5][0-9]:[0-5][0-9][.,][0-9]{3}"
_TIME_LINE = re.compile(rf"^({_STAMP})[ \t]+-->[ \t]+({_STAMP})(?:[ \t]+(.*))?$")


@dataclass(frozen=True)
class Cue:
    start: int
    end: int
    text: str
    identifier: str = ""
    settings: str = ""


def _decode(path: Path, override: str) -> str:
    with path.open("rb") as source:
        raw = source.read(_MAX_SUBTITLE_BYTES + 1)
    if len(raw) > _MAX_SUBTITLE_BYTES:
        raise ToolError("Choose a subtitle file of 8 MiB or smaller")
    try:
        if override:
            text = raw.decode(override)
        elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16")
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode(detect_encoding(path) or "utf-8")
    except (LookupError, ValueError):
        raise ToolError("The subtitle text encoding could not be read. Choose the original encoding.") from None
    if "\x00" in text:
        raise ToolError("Choose a text subtitle file")
    return text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def _milliseconds(stamp: str) -> int:
    clock, fraction = stamp.replace(",", ".").split(".")
    seconds = 0
    for value in clock.split(":"):
        seconds = seconds * 60 + int(value)
    return 1000 * seconds + int(fraction)


def _timecode(milliseconds: int, vtt: bool) -> str:
    seconds, fraction = divmod(milliseconds, 1000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    sep = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{sep}{fraction:03d}"


def _parse_cues(text: str, *, vtt: bool, trim: bool) -> tuple[list[str], list[Cue]]:
    blocks = _BLOCKS.split(text.strip("\n"))
    metadata = []
    if vtt:
        header = blocks.pop(0)
        first = header.split("\n", 1)[0]
        if not re.fullmatch(r"WEBVTT(?:[ \t].*)?", first):
            raise ToolError("This file is missing its WebVTT header")
        metadata.append(header)
    cues = []
    for block in blocks:
        if not block.strip():
            continue
        lines = block.split("\n")
        if vtt and (lines[0] in {"STYLE", "REGION", "NOTE"} or re.match(r"NOTE[ \t]", lines[0])):
            metadata.append(block)
            continue
        number = len(cues) + 1
        if number > _MAX_CUES:
            raise ToolError(f"Choose a subtitle file with at most {_MAX_CUES:,} cues")
        identifier = ""
        if "-->" not in lines[0]:
            identifier = lines.pop(0)
        match = _TIME_LINE.fullmatch(lines[0].strip()) if lines else None
        if match is None:
            raise ToolError(f"Cue {number} has an invalid start or end time")
        start, end, settings = match.groups()
        start_ms, end_ms = _milliseconds(start), _milliseconds(end)
        if end_ms <= start_ms:
            raise ToolError(f"Cue {number} must end after it starts")
        payload = "\n".join(line.strip() if trim else line for line in lines[1:])
        cues.append(Cue(start_ms, end_ms, payload, identifier if vtt else "", settings or ""))
    return metadata, cues


@register
class SubtitleCleanup(Tool):
    slug = "subtitle-cleanup"
    name = "Clean subtitle cues"
    category = "subtitles"
    description = "Sort and renumber captions, remove repeated cues, and shift their timing. Keeps SRT or WebVTT."
    accepts: ClassVar[list[str]] = [".srt", ".vtt"]
    params_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "offset_ms": {
                "type": "integer",
                "title": "Timing offset (ms)",
                "description": "Use a positive value for later captions or a negative value for earlier captions.",
                "minimum": -600_000,
                "maximum": 600_000,
                "default": 0,
            },
            "remove_duplicates": {
                "type": "boolean",
                "title": "Remove identical cues",
                "default": True,
            },
            "trim_whitespace": {
                "type": "boolean",
                "title": "Trim whitespace on text lines",
                "default": True,
            },
            "encoding": {
                "type": "string",
                "title": "Input text encoding",
                "description": "Leave blank for automatic detection, or enter a name such as windows-1252.",
                "pattern": "^[A-Za-z0-9_-]*$",
                "maxLength": 32,
                "default": "",
            },
        },
        "additionalProperties": False,
    }

    def run(self, ctx: ToolContext) -> None:
        path = ctx.input_paths[0]
        vtt = path.suffix.lower() == ".vtt"
        offset = ctx.params.get("offset_ms", 0)
        if type(offset) is not int or not -600_000 <= offset <= 600_000:
            raise ToolError("Choose an offset between -600,000 and 600,000 milliseconds")
        metadata, cues = _parse_cues(
            _decode(path, ctx.params.get("encoding", "")),
            vtt=vtt,
            trim=ctx.params.get("trim_whitespace", True),
        )
        if not cues:
            raise ToolError("This subtitle file has no cues")
        ctx.progress(0.55, "Cleaning and sorting subtitle cues")
        cleaned = [
            Cue(max(0, cue.start + offset), cue.end + offset, cue.text, cue.identifier, cue.settings)
            for cue in cues
            if cue.end + offset > 0 and cue.text.strip()
        ]
        if ctx.params.get("remove_duplicates", True):
            cleaned = list(dict.fromkeys(cleaned))
        if not cleaned:
            raise ToolError("No subtitle cues remain. Try a smaller timing offset.")
        cleaned.sort(key=lambda cue: cue.start)
        pending = ctx.workdir / f"cleaned{path.suffix.lower()}"
        with pending.open("w", encoding="utf-8", newline="\n") as target:
            if metadata:
                target.write("\n\n".join(metadata) + "\n\n")
            for index, cue in enumerate(cleaned, 1):
                identifier = cue.identifier if vtt else str(index)
                if identifier:
                    target.write(identifier + "\n")
                settings = f" {cue.settings}" if cue.settings else ""
                target.write(f"{_timecode(cue.start, vtt)} --> {_timecode(cue.end, vtt)}{settings}\n{cue.text}\n\n")
        guard_output_size(pending, "cleaned subtitle file")
        pending.replace(ctx.output_dir / f"{path.stem}-cleaned{path.suffix.lower()}")
        ctx.progress(1, f"Saved {len(cleaned)} cues")
