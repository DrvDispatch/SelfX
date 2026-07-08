"""voice-isolation: split audio into vocals and accompaniment with audio-separator (UVR models)."""

from ._media import guard_output_size
from .base import Tool, ToolContext, ToolError
from .registry import register

# Per-worker cache of loaded Separators keyed by (model filename, output format), so a
# warm worker reuses the (expensive) loaded ONNX model across jobs instead of reloading
# it every request. Keying on the format too avoids two concurrent jobs (in a
# non-forking worker) racing on a shared instance's output_format. output_dir is still
# updated per job on the reused instance.
_SEPARATORS: dict = {}

# hints that a failure is a model download / network problem rather than bad input.
_NETWORK_HINTS = ("download", "connection", "network", "resolve", "timed out",
                  "timeout", "http", "urlopen", "ssl", "getaddrinfo")


def _get_separator(model: str, output_dir: str, output_format: str):
    from audio_separator.separator import Separator

    key = (model, output_format)
    sep = _SEPARATORS.get(key)
    if sep is None:
        sep = Separator(output_dir=output_dir, output_format=output_format)
        sep.load_model(model_filename=model)
        _SEPARATORS[key] = sep
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
            "rename_outputs": {
                "type": "boolean",
                "title": "Tidy output names",
                "description": ("Rename the produced tracks to predictable {name}-vocals / "
                                "{name}-instrumental so results are easy to tell apart. "
                                "Off keeps the separator's original filenames."),
                "default": False,
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
        rename_outputs = bool(ctx.params.get("rename_outputs", False))
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

        # Optionally give the two stems predictable, human-readable names so the UI
        # can label them, instead of the separator's opaque "{stem}_(Vocals)_{model}"
        # form. Only rename when we can confidently classify a file by its name.
        if rename_outputs:
            renamed = []
            for p in produced:
                low = p.name.lower()
                if "vocal" in low:
                    target = ctx.output_dir / f"{src.stem}-vocals{p.suffix.lower()}"
                elif "instrument" in low or "no_vocal" in low or "no vocals" in low:
                    target = ctx.output_dir / f"{src.stem}-instrumental{p.suffix.lower()}"
                else:
                    renamed.append(p)
                    continue
                if target != p and not target.exists():
                    try:
                        p.replace(target)
                        renamed.append(target)
                        continue
                    except OSError:
                        pass
                renamed.append(p)
            produced = renamed

        for p in produced:
            guard_output_size(p, "separated track")
        ctx.progress(1.0, f"produced {len(outputs) or len(produced)} track(s)")
