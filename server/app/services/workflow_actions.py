"""Typed, local actions shared by the prompt planner and workflow worker."""

import importlib.util
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft7Validator

from ..config import settings
from ..tools import _media
from ..tools.base import ToolContext, ToolError
from ..tools.registry import get_tool

MAX_STEPS = 6
_ID = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_MAX_MEDIA_SECONDS = 3600
_MAX_PDF_PAGES = 250
_MIB = 1024 * 1024
_SPEECH_ACTIONS = {"transcribe", "transcript-pdf"}


@dataclass(frozen=True)
class Action:
    outputs: tuple[tuple[str, str], ...]
    fields: tuple[str, ...]
    binaries: tuple[str, ...] = ()
    format_parameter: str | None = None
    formats: tuple[str, ...] = ()
    input_extensions: tuple[str, ...] = ()
    media_track: str | None = None


_ACTIONS = {
    "pdf-compress": Action((("pdf", ".pdf"),), ("quality", "fast_web_view"), ("gs",)),
    "pdf-organize": Action((("pdf", ".pdf"),), ("page_order", "remove_pages")),
    "pdf-rotate": Action((("pdf", ".pdf"),), ("angle", "pages", "which", "linearize")),
    "pdf-extract-text": Action((("text", ".txt"),), ("pages",)),
    "ocr-pdf": Action((("pdf", ".pdf"),), ("language", "deskew", "rotate_pages"), ("ocrmypdf", "tesseract", "gs")),
    "image-convert": Action(
        (("image", ""),), ("format", "quality", "max_width", "max_height", "strip_metadata"),
        format_parameter="format", formats=("png", "jpg", "webp"),
        input_extensions=(".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"),
    ),
    "image-optimize": Action(
        (("image", ""),), ("quality", "target_kb", "png_compress_level"),
        input_extensions=(".jpg", ".png", ".webp"),
    ),
    "video-trim": Action(
        (("video", ".mp4"),), ("start", "duration", "end", "crf"), ("ffmpeg", "ffprobe"), media_track="video",
    ),
    "video-target-size": Action(
        (("video", ".mp4"),), ("target_mb", "max_resolution", "keep_audio"), ("ffmpeg", "ffprobe"), media_track="video",
    ),
    "audio-extract": Action(
        (("audio", ""),), ("format", "bitrate", "sample_rate", "channels"), ("ffmpeg", "ffprobe"),
        format_parameter="format", formats=("mp3", "aac", "m4a", "wav", "flac", "opus"), media_track="audio",
    ),
    "subtitle-convert": Action(
        (("subtitles", ""),), ("to", "encoding"), ("ffmpeg",),
        format_parameter="to", formats=("srt", "vtt", "ass"),
    ),
    "subtitle-cleanup": Action(
        (("subtitles", ""),), ("offset_ms", "remove_duplicates", "trim_whitespace", "encoding"),
    ),
    "transcribe": Action(
        (("transcript", ""),), ("language", "output", "task"), ("ffmpeg", "ffprobe"),
        format_parameter="output", formats=("txt", "srt", "vtt", "json"), media_track="audio",
    ),
    "transcript-pdf": Action(
        (("pdf", ".pdf"), ("captions", ".srt"), ("transcript", ".json")),
        ("language", "title"), ("ffmpeg", "ffprobe"), media_track="audio",
    ),
    "transcript-export": Action((("pdf", ".pdf"), ("captions", ".srt")), ("title",)),
}


def _action_info(slug: str) -> dict | None:
    action = _ACTIONS.get(slug)
    if action is None or any(not shutil.which(program) for program in action.binaries):
        return None
    tool = get_tool("transcribe" if slug == "transcript-pdf" else slug)
    if not tool or not tool.available()[0]:
        return None
    if slug in _SPEECH_ACTIONS and importlib.util.find_spec("faster_whisper") is None:
        return None
    if slug in ("transcript-pdf", "transcript-export") and importlib.util.find_spec("reportlab") is None:
        return None
    if slug == "pdf-extract-text" and not any(importlib.util.find_spec(lib) for lib in ("fitz", "pypdf")):
        return None

    tool_properties = tool.params_schema["properties"]
    properties = {field: dict(tool_properties[field]) for field in action.fields if field in tool_properties}
    if slug == "transcript-pdf":
        properties["title"] = {"type": "string", "maxLength": 160, "description": "Optional PDF title"}
    if action.format_parameter:
        properties[action.format_parameter]["enum"] = list(action.formats)
    if slug == "video-trim":
        properties["duration"]["maximum"] = _MAX_MEDIA_SECONDS
    inputs = list(action.input_extensions or tool.accepts)
    outputs = []
    for role, extension in action.outputs:
        extensions = [extension] if extension else ["." + fmt for fmt in action.formats] or inputs
        spec = {"role": role, "extensions": extensions}
        if action.format_parameter:
            spec["format_parameter"] = action.format_parameter
        outputs.append(spec)
    return {
        "slug": slug,
        "name": "Transcript PDF and captions" if slug == "transcript-pdf" else tool.name,
        "description": (
            "Transcribe audio or video once and export a timestamped PDF, SRT captions and timed JSON."
            if slug == "transcript-pdf" else tool.description
        ),
        "input_extensions": inputs,
        "outputs": outputs,
        "params_schema": {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
            "required": [key for key in tool.params_schema.get("required", ()) if key in properties],
        },
    }


def action_catalog() -> list[dict]:
    """Return capabilities present in the current app image, without model secrets."""
    return [info for slug in _ACTIONS if (info := _action_info(slug)) is not None]


def _output_types(action: Action, params: dict, input_extension: str) -> dict[str, str]:
    variable = "." + params[action.format_parameter] if action.format_parameter else input_extension
    return {role: extension or variable for role, extension in action.outputs}


def validate_plan(plan: dict, source_name: str) -> dict:
    """Validate and normalize a bounded plan of named file-to-file actions."""
    steps = plan.get("steps") if isinstance(plan, dict) and set(plan) == {"steps"} else None
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ToolError("A workflow needs between 1 and 6 steps")
    file_types = {"source": Path(source_name).suffix.lower()}
    ids = set()
    normalized = []
    for number, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or set(step) != {"id", "action", "input", "params"}:
            raise ToolError(f"Step {number} must specify an ID, action, input and parameters")
        step_id, slug, source, supplied = (step[key] for key in ("id", "action", "input", "params"))
        if not isinstance(step_id, str) or not _ID.fullmatch(step_id) or step_id in ids:
            raise ToolError(f"Step {number} has an invalid or duplicate ID")
        info = _action_info(slug) if isinstance(slug, str) else None
        if info is None:
            raise ToolError(f"Step {number} needs an available workflow action")
        if not isinstance(source, str) or source not in file_types:
            raise ToolError(f"Step {number} must use the source or an earlier output")
        extension = file_types[source]
        if extension not in info["input_extensions"]:
            raise ToolError(f"Step {number} cannot use {extension or 'this file type'} with {info['name']}")
        if not isinstance(supplied, dict) or any(
            isinstance(value, float) and not math.isfinite(value) for value in supplied.values()
        ):
            raise ToolError(f"Step {number} has invalid parameters")
        schema = info["params_schema"]
        params = {key: field["default"] for key, field in schema["properties"].items() if "default" in field}
        params.update(supplied)
        if not Draft7Validator(schema).is_valid(params):
            raise ToolError(f"Step {number} has unsupported or invalid parameters for {info['name']}")
        if slug == "pdf-organize" and not (params["page_order"].strip() or params["remove_pages"].strip()):
            raise ToolError(f"Step {number} needs pages to keep in order or remove")
        if slug == "image-optimize" and "target_kb" in params and extension not in {".jpg", ".webp"}:
            raise ToolError(f"Step {number} needs a JPEG or WebP input for its file size limit")
        if slug == "video-trim":
            from ..tools.video_trim import _to_seconds

            if ("end" in params) == ("duration" in params):
                raise ToolError(f"Step {number} needs exactly one end time or duration")
            start = _to_seconds(_media.validate_time(params["start"]))
            if "end" in params:
                end = _to_seconds(_media.validate_time(params["end"], "end"))
                if not 0 < end - start <= _MAX_MEDIA_SECONDS:
                    raise ToolError(f"Step {number} needs a clip under 60 minutes with an end after its start")
        if slug == "subtitle-convert" and extension == "." + params["to"]:
            raise ToolError(f"Step {number} already has subtitles in the selected format")
        if slug in _SPEECH_ACTIONS:
            from ..tools.transcribe import _resolve_language

            params["language"] = _resolve_language(params["language"]) or "auto"
        ids.add(step_id)
        for role, output_type in _output_types(_ACTIONS[slug], params, extension).items():
            file_types[f"{step_id}.{role}"] = output_type
        normalized.append({"id": step_id, "action": slug, "input": source, "params": params})
    return {"steps": normalized}


class _LocalToolContext(ToolContext):
    def run_cmd(self, args, timeout=None, **kwargs):
        if args and Path(args[0]).stem.lower() in ("ffmpeg", "ffprobe") and "-protocol_whitelist" not in args:
            args = [args[0], *_media.LOCAL_INPUT_OPTIONS, *args[1:]]
        return super().run_cmd(args, timeout, **kwargs)


def _preflight(ctx: ToolContext, path: Path, action: Action) -> dict | None:
    size = path.stat().st_size
    if size == 0 or size > settings.max_upload_bytes:
        raise ToolError("The action input is empty or exceeds the file size limit")
    if path.suffix.lower() == ".pdf":
        import pikepdf

        try:
            with pikepdf.open(path) as pdf:
                if pdf.is_encrypted:
                    raise ToolError("Use the manual PDF tool for a protected document")
                if len(pdf.pages) > _MAX_PDF_PAGES:
                    raise ToolError(f"Workflow PDF inputs can have at most {_MAX_PDF_PAGES} pages")
        except pikepdf.PasswordError:
            raise ToolError("Use the manual PDF tool for a protected document") from None
        except pikepdf.PdfError:
            raise ToolError("The action input is not a valid PDF") from None
    if action.media_track:
        info = _media.probe(ctx, path)
        duration = info["duration"]
        if not info[action.media_track] or duration is None or not 0 < duration <= _MAX_MEDIA_SECONDS:
            raise ToolError(f"Choose a readable recording with a {action.media_track} track under 60 minutes")
        if (info["width"] or 0) * (info["height"] or 0) > 8_847_360:
            raise ToolError("Video workflow inputs can be at most 4K")
        return info
    return None


def prepare_speech(ctx: ToolContext, source: Path) -> Path:
    """Preflight and decode an owned recording into local bounded PCM for Whisper."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ToolError("The speech worker needs FFmpeg and FFprobe")
    workdir = ctx.workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    local = _LocalToolContext(ctx.job_id, [source.resolve()], {}, workdir, ctx.output_dir, ctx.progress)
    info = _preflight(local, local.input_paths[0], _ACTIONS["transcribe"])
    assert info is not None
    if shutil.disk_usage(workdir).free < int(32000 * info["duration"]) + 32 * _MIB:
        raise ToolError("Free up disk space before transcribing this recording")
    audio = workdir / "speech.wav"
    ctx.progress(0.04, "Preparing audio")
    local.run_cmd([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(local.input_paths[0]), "-map", "0:a:0", "-t", str(_MAX_MEDIA_SECONDS),
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio),
    ])
    return audio


def _run_step(slug: str, ctx: ToolContext) -> dict[str, Path]:
    path = ctx.input_paths[0]
    if slug in _SPEECH_ACTIONS:
        audio = prepare_speech(ctx, path)
        ctx.params["source_name"] = ctx.params.get("source_name") or path.name
        ctx.input_paths = [audio]
        try:
            if slug == "transcript-pdf":
                from ..tools._transcript_pdf import run_transcript_pdf

                run_transcript_pdf(ctx)
                return {"pdf": ctx.output_dir / "transcript.pdf",
                        "captions": ctx.output_dir / "captions.srt",
                        "transcript": ctx.output_dir / "transcript.json"}
            tool = get_tool(slug)
            assert tool is not None
            tool.run(ctx)
        finally:
            audio.unlink(missing_ok=True)
    else:
        tool = get_tool(slug)
        assert tool is not None
        tool.run(ctx)
        if slug == "transcript-export":
            return {"pdf": ctx.output_dir / "transcript.pdf", "captions": ctx.output_dir / "captions.srt"}

    role = _ACTIONS[slug].outputs[0][0]
    results = list(ctx.output_dir.iterdir())
    if len(results) != 1:
        raise ToolError("The action did not produce its expected file")
    return {role: results[0]}


def run_action_plan(ctx: ToolContext, plan: dict) -> None:
    """Execute an ordered graph into this attempt's staged output directory."""
    if len(ctx.input_paths) != 1:
        raise ToolError("A workflow takes exactly one source file")
    source = ctx.input_paths[0].resolve()
    source_name = str(ctx.params.get("source_name") or source.name)
    steps = validate_plan(plan, source_name)["steps"]
    output_dir = ctx.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {"source": source}
    consumed = 0
    maximum = _media.max_output_bytes()
    for index, step in enumerate(steps):
        slug = step["action"]
        action = _ACTIONS[slug]
        path = files[step["input"]]
        workdir = (ctx.workdir / f"step-{index + 1}").resolve()
        out = workdir / "exports"
        out.mkdir(parents=True)
        label = f"Step {index + 1}/{len(steps)}"

        def report(fraction: float, message: str, *, index: int = index, label: str = label) -> None:
            ctx.progress((index + fraction) / len(steps), f"{label} · {message}")

        step_ctx = _LocalToolContext(ctx.job_id, [path], dict(step["params"]), workdir, out, report)
        if slug == "transcript-pdf":
            step_ctx.params["source_name"] = source_name
        step_ctx.progress(0, "Preparing input")
        try:
            if shutil.disk_usage(workdir).free < min(maximum - consumed, 32 * _MIB):
                raise ToolError("Free up disk space to continue this workflow")
            if slug not in _SPEECH_ACTIONS:
                _preflight(step_ctx, path, action)
            artifacts = _run_step(slug, step_ctx)
            types = _output_types(action, step["params"], path.suffix.lower())
            for role, artifact in artifacts.items():
                if artifact.is_symlink() or not artifact.is_file() or artifact.suffix.lower() != types[role]:
                    raise ToolError("The action did not produce its expected file type")
                size = artifact.stat().st_size
                if size == 0 or consumed + size > maximum:
                    raise ToolError("The action output is empty or exceeds the workflow output limit")
                consumed += size
                target = output_dir / f"{step['id']}-{role}{types[role]}"
                artifact.replace(target)
                files[f"{step['id']}.{role}"] = target
        except ToolError as exc:
            raise ToolError(f"{label}: {exc}") from None
        if consumed == maximum and index + 1 < len(steps):
            raise ToolError("The workflow reached its output size limit")
        step_ctx.progress(1, "Complete")
