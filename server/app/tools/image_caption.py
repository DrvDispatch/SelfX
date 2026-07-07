"""image-caption: describe an image in words using a local vision model (Ollama)."""

import base64

import httpx

from ..config import settings
from .base import Tool, ToolContext, ToolError
from .registry import register

_VISION_MODEL = "moondream"


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
            }
        },
    }

    def available(self) -> tuple[bool, str | None]:
        try:
            r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=2.0)
            if r.status_code == 200:
                names = [m.get("name", "") for m in r.json().get("models", [])]
                if any(n.startswith(_VISION_MODEL) for n in names):
                    return True, None
                return False, f"the vision model '{_VISION_MODEL}' is not pulled in Ollama"
        except Exception:
            pass
        return False, "the local AI service (Ollama) is not running"

    def run(self, ctx: ToolContext) -> None:
        prompt = str(ctx.params.get("prompt", "Describe this image in one or two sentences."))
        src = ctx.input_paths[0]
        b64 = base64.b64encode(src.read_bytes()).decode("ascii")
        ctx.progress(0.4, "describing image with local AI")
        try:
            r = httpx.post(
                f"{settings.ollama_url}/api/generate",
                json={"model": _VISION_MODEL, "prompt": prompt, "images": [b64],
                      "stream": False, "keep_alive": settings.ollama_keep_alive},
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
