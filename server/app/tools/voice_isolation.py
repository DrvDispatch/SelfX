"""voice-isolation: split audio into vocals and accompaniment with audio-separator (UVR models)."""

from .base import Tool, ToolContext, ToolError
from .registry import register

# Per-worker cache of loaded Separators keyed by model filename, so a warm worker
# reuses the (expensive) loaded ONNX model across jobs instead of reloading it every
# request. output_dir/format are updated per job on the reused instance.
_SEPARATORS: dict = {}

# hints that a failure is a model download / network problem rather than bad input.
_NETWORK_HINTS = ("download", "connection", "network", "resolve", "timed out",
                  "timeout", "http", "urlopen", "ssl", "getaddrinfo")


def _get_separator(model: str, output_dir: str, output_format: str):
    from audio_separator.separator import Separator

    sep = _SEPARATORS.get(model)
    if sep is None:
        sep = Separator(output_dir=output_dir, output_format=output_format)
        sep.load_model(model_filename=model)
        _SEPARATORS[model] = sep
    # reuse the loaded model but point it at this job's output dir/format
    try:
        sep.output_dir = output_dir
        sep.output_format = output_format
    except Exception:
        pass
    return sep


@register
class VoiceIsolation(Tool):
    slug = "voice-isolation"
    name = "Isolate vocals / instrumental"
    category = "media"
    description = "Separate a song into vocal and instrumental tracks using AI source separation."
    accepts = [".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".mp4", ".mkv", ".webm"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "title": "Model",
                "enum": ["UVR-MDX-NET-Inst_HQ_3.onnx", "UVR_MDXNET_KARA_2.onnx"],
                "default": "UVR-MDX-NET-Inst_HQ_3.onnx",
            },
            "output_format": {
                "type": "string",
                "title": "Output format",
                "description": "WAV/FLAC keep full quality; MP3 is smaller.",
                "enum": ["mp3", "wav", "flac"],
                "default": "mp3",
            },
        },
    }

    def available(self) -> tuple[bool, str | None]:
        try:
            import audio_separator  # noqa: F401
            return True, None
        except Exception:
            return False, "the source-separation engine (audio-separator) is not installed"

    def run(self, ctx: ToolContext) -> None:
        model = str(ctx.params.get("model", "UVR-MDX-NET-Inst_HQ_3.onnx"))
        out_fmt = str(ctx.params.get("output_format", "mp3")).upper()
        src = ctx.input_paths[0]
        ctx.progress(0.2, "loading model (first run downloads it)")
        try:
            sep = _get_separator(model, str(ctx.output_dir), out_fmt)
            ctx.progress(0.4, "separating vocals from instrumental (this can take a while)")
            outputs = sep.separate(str(src))
        except Exception as exc:  # noqa: BLE001
            detail = str(exc).splitlines()[-1][:160] if str(exc) else ""
            if any(h in detail.lower() for h in _NETWORK_HINTS):
                raise ToolError(
                    "the separation model could not be downloaded — it must be "
                    "pre-installed for offline use"
                ) from None
            raise ToolError(f"source separation failed: {detail or 'unknown error'}") from None
        produced = [p for p in ctx.output_dir.iterdir() if p.is_file()]
        if not produced:
            raise ToolError("separation produced no output")
        ctx.progress(1.0, f"produced {len(outputs) or len(produced)} track(s)")
