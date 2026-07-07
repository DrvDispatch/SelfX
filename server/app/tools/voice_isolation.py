"""voice-isolation: split audio into vocals and accompaniment with audio-separator (UVR models)."""

from .base import Tool, ToolContext, ToolError
from .registry import register


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
            }
        },
    }

    def available(self) -> tuple[bool, str | None]:
        try:
            import audio_separator  # noqa: F401
            return True, None
        except Exception:
            return False, "the source-separation engine (audio-separator) is not installed"

    def run(self, ctx: ToolContext) -> None:
        from audio_separator.separator import Separator

        model = str(ctx.params.get("model", "UVR-MDX-NET-Inst_HQ_3.onnx"))
        src = ctx.input_paths[0]
        ctx.progress(0.2, "loading model (first run downloads it)")
        try:
            sep = Separator(output_dir=str(ctx.output_dir), output_format="MP3")
            sep.load_model(model_filename=model)
            ctx.progress(0.4, "separating vocals from instrumental (this can take a while)")
            outputs = sep.separate(str(src))
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"source separation failed: {str(exc).splitlines()[-1][:160]}") from None
        produced = [p for p in ctx.output_dir.iterdir() if p.is_file()]
        if not produced:
            raise ToolError("separation produced no output")
        ctx.progress(1.0, f"produced {len(outputs) or len(produced)} track(s)")
