"""image-caption: describe an image in words using a local vision model (Ollama)."""

import base64
from io import BytesIO

import httpx

from ..config import settings
from ._imaging import downscale_max, flatten_rgb, load_image
from .base import Tool, ToolContext, ToolError
from .registry import register

# Preferred vision models, best first. Qwen2.5-VL is far stronger than moondream
# (richer descriptions, multilingual, in-image OCR, chart/table reading); moondream
# stays as the small/fast fallback so the tool works even before the bigger model
# is pulled.
_PREFERRED_MODELS = ("qwen2.5vl:7b", "qwen2.5vl", "llama3.2-vision", "moondream")
_FALLBACK_MODEL = "moondream"
# Downscaling here cuts the base64 payload (a large upload would otherwise become a
# multi-hundred-MB JSON body) and sidesteps BMP/TIFF/GIF decode issues by always
# re-encoding to JPEG.
_MAX_DIM = 1536


def _installed_models() -> list[str]:
    try:
        r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=2.0)
        if r.status_code == 200:
            return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


def _best_vision_model(installed: list[str]) -> str | None:
    """Best installed vision model by preference order, matching on name prefix."""
    for pref in _PREFERRED_MODELS:
        for name in installed:
            if name == pref or name.startswith(pref + ":") or name.startswith(pref):
                return name
    return None


@register
class ImageCaption(Tool):
    slug = "image-caption"
    name = "Describe image (AI)"
    category = "images"
    description = "Generate a text description / caption for an image with a local vision model."
    accepts = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "title": "Question / instruction",
                "description": "What to ask about the image",
                "default": "Describe this image in one or two sentences.",
                "maxLength": 500,
            },
            "model": {
                "type": "string",
                "title": "Vision model",
                "description": (
                    "Ollama vision model to use; leave blank to auto-pick the best "
                    "installed (Qwen2.5-VL if pulled, else moondream). "
                    "Any named model must already be pulled."
                ),
                "maxLength": 100,
            },
            "system": {
                "type": "string",
                "title": "System prompt",
                "description": "Optional system instruction (e.g. 'reply as alt-text only')",
                "maxLength": 1000,
            },
            "temperature": {
                "type": "number",
                "title": "Temperature",
                "description": "Higher = more creative; leave blank for the model default",
                "minimum": 0,
                "maximum": 2,
            },
            "num_predict": {
                "type": "integer",
                "title": "Max tokens",
                "description": "Cap the response length; leave blank for the model default",
                "minimum": 1,
                "maximum": 4096,
            },
        },
    }

    def available(self) -> tuple[bool, str | None]:
        installed = _installed_models()
        if not installed:
            return False, "the local AI service (Ollama) is not running"
        if _best_vision_model(installed):
            return True, None
        return False, f"no vision model is pulled in Ollama (try one of: {', '.join(_PREFERRED_MODELS)})"

    def run(self, ctx: ToolContext) -> None:
        prompt = str(ctx.params.get("prompt", "Describe this image in one or two sentences."))
        # explicit user choice wins; otherwise pick the best installed vision model
        model = str(ctx.params.get("model") or "").strip()
        if not model:
            model = _best_vision_model(_installed_models()) or _FALLBACK_MODEL
        src = ctx.input_paths[0]
        # normalise + downscale to a small RGB JPEG before base64 (EXIF-correct,
        # bomb-guarded, ~100x smaller payload than sending the raw upload)
        img = flatten_rgb(downscale_max(load_image(src), _MAX_DIM))
        buf = BytesIO()
        img.save(buf, "JPEG", quality=90)
        img.close()
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        payload: dict = {
            "model": model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "keep_alive": settings.ollama_keep_alive,
        }
        system = str(ctx.params.get("system") or "").strip()
        if system:
            payload["system"] = system
        options: dict = {}
        temperature = ctx.params.get("temperature")
        if temperature is not None:
            try:
                options["temperature"] = max(0.0, min(2.0, float(temperature)))
            except (TypeError, ValueError):
                pass
        num_predict = ctx.params.get("num_predict")
        if num_predict is not None:
            try:
                options["num_predict"] = max(1, min(4096, int(num_predict)))
            except (TypeError, ValueError):
                pass
        if options:
            payload["options"] = options

        ctx.progress(0.4, "describing image with local AI")
        try:
            r = httpx.post(
                f"{settings.ollama_url}/api/generate",
                json=payload,
                timeout=httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=5.0),
            )
        except httpx.HTTPError:
            raise ToolError("could not reach the local AI service") from None
        if r.status_code != 200:
            raise ToolError("the vision model returned an error")
        try:
            caption = r.json()["response"].strip()
        except (KeyError, ValueError):
            raise ToolError("unexpected response from the vision model") from None
        if not caption:
            raise ToolError("the model returned an empty caption")
        (ctx.output_dir / f"{src.stem}-caption.txt").write_text(caption, encoding="utf-8")
        ctx.progress(1.0, "done")
