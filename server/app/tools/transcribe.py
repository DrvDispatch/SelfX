"""transcribe: speech-to-text for audio/video with faster-whisper (SPEC §8).

The model is loaded once per worker process and cached. First use downloads the
model weights, so the first job is slower.
"""

import json
import os
from pathlib import Path
from time import monotonic

from ..config import settings
from ._media import probe
from .base import Tool, ToolContext, ToolError
from .registry import register

_MODELS: dict[str, object] = {}  # WhisperModel cache keyed by model name (per worker)

# Whisper sizes offered to users. The operator can configure a custom default.
_WHISPER_MODELS = ["large-v3-turbo", "large-v3", "medium", "small", "base", "tiny"]
_EXPORT_FORMATS = ("txt", "srt", "vtt", "json")


def _select_model(requested: str, task: str) -> str:
    configured = settings.whisper_model.strip()
    model = configured if requested in ("", "auto") else requested
    if model not in _WHISPER_MODELS and "/" not in model:
        model = "small"
    if task == "translate" and (
        "turbo" in model.lower() or model.lower().endswith(".en")
    ):
        return "medium" if settings.whisper_device.lower().startswith("cuda") else "small"
    return model


def _cpu_threads() -> int:
    """A sane per-worker thread cap so concurrent heavy workers don't oversubscribe
    the CPU (CTranslate2's default of 0 grabs every core for each worker)."""
    cores = os.cpu_count() or 4
    return max(1, min(8, cores // 2))


def _get_model(model_name: str):
    model = _MODELS.get(model_name)
    if model is None:
        try:
            from faster_whisper import WhisperModel
        except Exception:
            raise ToolError("the transcription engine is not available on this server") from None
        try:
            model = WhisperModel(
                model_name,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute,
                cpu_threads=_cpu_threads(),
                num_workers=1,
                local_files_only=settings.whisper_local_only,
            )
        except Exception:
            if settings.whisper_local_only:
                raise ToolError(f"could not load '{model_name}' from the local model cache") from None
            raise ToolError(f"could not load the '{model_name}' transcription model") from None
        _MODELS[model_name] = model
    return model


def _resolve_language(language: str) -> str | None:
    """Normalize the language param to a code (or None for auto); raise on invalid.

    Validation is best-effort: if faster-whisper's code table isn't importable we
    pass the value through and let the engine decide.
    """
    lang = language.strip().lower()
    if lang in ("", "auto"):
        return None
    try:
        from faster_whisper.tokenizer import _LANGUAGE_CODES as codes
    except Exception:
        codes = None
    if codes and lang not in codes:
        raise ToolError(
            f"unsupported language code '{language}' — use a 2-letter ISO code such as "
            f"en, de, fr, es, ar, zh, ru, ja, or 'auto' to detect it automatically"
        )
    return lang


def _ts(seconds: float, sep: str) -> str:
    """Format seconds as HH:MM:SS,mmm (srt, sep=',') or HH:MM:SS.mmm (vtt, sep='.')."""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def write_transcript(path: Path, output: str, transcript: dict) -> None:
    """Write an export from a transcript without invoking the engine."""
    segments = transcript["segments"]
    with path.open("w", encoding="utf-8") as stream:
        if output == "txt":
            stream.write("\n".join(segment["text"] for segment in segments))
        elif output == "json":
            json.dump(transcript, stream, ensure_ascii=False, indent=2)
        else:
            sep = "," if output == "srt" else "."
            if output == "vtt":
                stream.write("WEBVTT\n\n")
            for i, segment in enumerate(segments, 1):
                if output == "srt":
                    stream.write(f"{i}\n")
                start = _ts(segment["start"] or 0, sep)
                end = _ts(segment["end"] or 0, sep)
                stream.write(f"{start} --> {end}\n{segment['text']}\n")
                if i < len(segments):
                    stream.write("\n")


@register
class Transcribe(Tool):
    slug = "transcribe"
    name = "Transcribe audio / video"
    category = "ai"
    description = "Transcribe speech from an audio or video file to text or subtitles (local Whisper)."
    accepts = [
        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".opus", ".m4a", ".wma", ".aiff",
        ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v",
    ]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "engine": {
                "type": "string",
                "title": "Engine",
                "description": "faster-whisper = fast, built in (default). whisperx = word-level "
                               "alignment + optional speaker diarization (runs in its own env).",
                "enum": ["faster-whisper", "whisperx"],
                "default": "faster-whisper",
            },
            "diarize": {
                "type": "boolean",
                "title": "Label speakers (WhisperX)",
                "description": "Tag who spoke each line. Needs the whisperx engine + a HuggingFace token.",
                "default": False,
            },
            "model": {
                "type": "string",
                "title": "Model",
                "description": "Smaller models finish faster and use less memory. "
                               "English translation uses a compatible model when needed.",
                "enum": ["auto", *_WHISPER_MODELS],
                "default": "auto",
            },
            "language": {
                "type": "string",
                "title": "Spoken language",
                "description": "Leave as auto or enter a code such as en (English), nl (Dutch), or fr (French).",
                "default": "auto",
                "maxLength": 10,
            },
            "output": {
                "type": "string",
                "title": "Output format",
                "enum": [*_EXPORT_FORMATS, "all"],
                "default": "txt",
            },
            "task": {
                "type": "string",
                "title": "Transcript language",
                "enum": ["transcribe", "translate"],
                "default": "transcribe",
            },
            "beam_size": {
                "type": "integer",
                "title": "Beam size",
                "description": "Decoding beam width; 0 = auto (5 on GPU, 1 on CPU). Higher is more accurate but slower.",
                "default": 0,
                "minimum": 0,
                "maximum": 10,
            },
            "word_timestamps": {
                "type": "boolean",
                "title": "Word-level timestamps",
                "description": "Also compute per-word timings (included in JSON output).",
                "default": False,
            },
            "condition_on_previous_text": {
                "type": "boolean",
                "title": "Condition on previous text",
                "description": "Use prior text as context. Turn off to reduce repetition loops on hard audio.",
                "default": True,
            },
            "initial_prompt": {
                "type": "string",
                "title": "Vocabulary hint",
                "description": "Optional names/jargon to bias spelling (e.g. product or people names).",
                "default": "",
                "maxLength": 800,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        output = str(ctx.params.get("output", "txt"))
        if output != "all" and output not in _EXPORT_FORMATS:
            raise ToolError(f"unsupported output format '{output}'")
        transcript = self.transcribe(ctx)
        ctx.progress(0.97, "exporting transcript")
        src = ctx.input_paths[0]
        for output_format in _EXPORT_FORMATS if output == "all" else (output,):
            write_transcript(ctx.output_dir / f"{src.stem}.{output_format}", output_format, transcript)
        ctx.progress(1.0, "done")

    def transcribe(self, ctx: ToolContext) -> dict:
        """Run the chosen engine once and return a transcript suitable for export."""
        language = str(ctx.params.get("language", "auto"))
        task = str(ctx.params.get("task", "transcribe")).strip().lower()
        if task not in ("transcribe", "translate"):
            task = "transcribe"
        word_timestamps = bool(ctx.params.get("word_timestamps", False))
        condition_prev = bool(ctx.params.get("condition_on_previous_text", True))
        initial_prompt = str(ctx.params.get("initial_prompt", "")).strip() or None
        engine = str(ctx.params.get("engine", "faster-whisper")).lower()
        diarize = bool(ctx.params.get("diarize", False))
        lang = _resolve_language(language)  # validates; raises a clear ToolError

        src = ctx.input_paths[0]

        # Cheap ffprobe preflight: fail fast with a precise message (and skip loading
        # the multi-hundred-MB model) when the file has no audio track at all.
        info_probe = probe(ctx, src)
        if (info_probe["video"] or info_probe["audio"] or info_probe["duration"] is not None) \
                and not info_probe["audio"]:
            raise ToolError("this file has no audio track to transcribe")

        model_name = _select_model(str(ctx.params.get("model") or "").strip(), task)

        if engine == "whisperx":
            segs, lang_out, total = self._run_whisperx(ctx, src, model_name, lang, task, diarize)
            word_timestamps = task == "transcribe"
        else:
            segs, lang_out, total = self._run_faster_whisper(
                ctx, src, model_name, lang, task, word_timestamps, condition_prev, initial_prompt
            )
        if not segs:
            raise ToolError("no speech was detected in the recording")

        segments = []
        for segment in segs:
            exported = {"start": segment.start, "end": segment.end, "text": segment.text.strip()}
            if getattr(segment, "speaker", None):
                exported["speaker"] = segment.speaker
            words = getattr(segment, "words", None)
            if word_timestamps and words:
                exported["words"] = [
                    {"start": word.start, "end": word.end, "word": word.word} for word in words
                ]
            segments.append(exported)
        return {"language": lang_out, "duration": total, "segments": segments}

    def _run_faster_whisper(self, ctx, src, model_name, lang, task,
                            word_timestamps, condition_prev, initial_prompt):
        """Built-in engine (main venv). Returns (segs, language, total_seconds)."""
        ctx.progress(0.05, "loading transcription model")
        model = _get_model(model_name)
        beam_override = ctx.params.get("beam_size", 0)
        try:
            beam_override = int(beam_override)
        except (TypeError, ValueError):
            beam_override = 0
        if beam_override > 0:
            beam_size = max(1, min(10, beam_override))
        else:
            beam_size = 5 if settings.whisper_device.lower().startswith("cuda") else 1

        ctx.progress(0.1, "decoding audio")
        try:
            segments, info = model.transcribe(
                str(src), language=lang, task=task, vad_filter=True, beam_size=beam_size,
                word_timestamps=word_timestamps, condition_on_previous_text=condition_prev,
                initial_prompt=initial_prompt,
            )
            total = getattr(info, "duration", 0) or 0
            segs = []
            last_update = 0.0
            progress = 0.1
            for seg in segments:
                segs.append(seg)
                now = monotonic()
                if now - last_update < 0.25:
                    continue
                if total:
                    progress = max(progress, min(0.95, (seg.end or 0) / total))
                else:
                    progress = min(0.9, 0.1 + 0.02 * len(segs))
                ctx.progress(progress, "transcribing")
                last_update = now
        except ToolError:
            raise
        except Exception:
            raise ToolError(
                "could not decode the audio — the file may have no audio track or be corrupt"
            ) from None
        return segs, getattr(info, "language", None), total

    def _run_whisperx(self, ctx, src, model_name, lang, task, diarize):
        """WhisperX in its ISOLATED venv (own torch) via subprocess. Returns
        (segs, language, total_seconds) with word alignment (+ speakers if diarized)."""
        from types import SimpleNamespace

        py = settings.whisperx_python
        runner = os.path.join(os.path.dirname(__file__), "_whisperx_run.py")
        if not os.path.isfile(py):
            raise ToolError("WhisperX is not installed on this server")
        # WhisperX loads faster-whisper sizes; map unknowns to large-v3.
        wx_models = {"large-v3", "large-v2", "large-v3-turbo", "medium", "small", "base", "tiny"}
        wx_model = model_name if model_name in wx_models else "large-v3"
        out_json = ctx.workdir / "whisperx.json"
        argv = [py, runner, "--audio", str(src), "--model", wx_model,
                "--language", lang or "auto", "--task", task,
                "--out", str(out_json), "--batch-size", "16"]
        if diarize:
            if not settings.huggingface_token:
                raise ToolError(
                    "speaker labels need a HuggingFace token — set HUGGINGFACE_TOKEN "
                    "(and accept the pyannote model terms), or turn off diarization"
                )
            # The token is inherited from the worker's env by the subprocess (the runner
            # reads HUGGINGFACE_TOKEN) so it never appears in the process args.
            argv += ["--diarize"]
        ctx.progress(0.2, "transcribing with WhisperX (word alignment)")
        ctx.run_cmd(argv)  # raises ToolError with stderr tail on failure
        try:
            data = json.loads(out_json.read_text("utf-8"))
        except Exception:
            raise ToolError("WhisperX produced no readable output") from None
        segs = []
        for s in data.get("segments", []):
            text = (s.get("text") or "").strip()
            speaker = s.get("speaker")
            if speaker:
                text = f"[{speaker}] {text}"
            words = [
                SimpleNamespace(word=w.get("word"), start=w.get("start"), end=w.get("end"))
                for w in (s.get("words") or [])
                if w.get("start") is not None
            ] or None
            segs.append(SimpleNamespace(start=s.get("start") or 0, end=s.get("end") or 0,
                                        text=text, words=words, speaker=speaker))
        total = segs[-1].end if segs else 0
        return segs, data.get("language"), total
