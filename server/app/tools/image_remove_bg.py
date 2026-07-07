"""image-remove-bg: remove an image background with rembg (U^2-Net, CPU/ONNX)."""

from ._imaging import downscale_max, load_image
from .base import Tool, ToolContext, ToolError
from .registry import register

# Cache one rembg session per model name for the lifetime of the worker so a warm
# worker reuses the loaded ONNX model instead of paying init cost every job.
_SESSIONS: dict[str, object] = {}
# Very large photos are matted at full resolution (slow / memory-heavy on CPU);
# bound the working size while leaving typical images untouched.
_MAX_DIM = 2048


def _session(model: str):
    sess = _SESSIONS.get(model)
    if sess is None:
        from rembg import new_session

        sess = new_session(model)
        _SESSIONS[model] = sess
    return sess


@register
class ImageRemoveBg(Tool):
    slug = "image-remove-bg"
    name = "Remove background"
    category = "images"
    description = "Automatically remove the background from a photo, leaving a transparent PNG."
    accepts = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "title": "Model",
                "description": "u2net = general, isnet-general-use = higher quality",
                "enum": ["u2net", "isnet-general-use", "u2netp", "silueta"],
                "default": "u2net",
            }
        },
    }

    def available(self) -> tuple[bool, str | None]:
        try:
            import rembg  # noqa: F401
            return True, None
        except Exception:
            return False, "the background-removal engine (rembg) is not installed"

    def run(self, ctx: ToolContext) -> None:
        from rembg import remove

        model = str(ctx.params.get("model", "u2net"))
        src = ctx.input_paths[0]
        # EXIF-correct, bomb-guarded load; downscale huge inputs to bound CPU/memory
        img = downscale_max(load_image(src), _MAX_DIM)
        ctx.progress(0.3, "removing background (first run downloads the model)")
        try:
            session = _session(model)
            result = remove(img, session=session)
        except Exception as exc:  # noqa: BLE001 - map to a friendly, labelled message
            msg = str(exc).lower()
            if any(k in msg for k in (
                "download", "url", "connection", "connect", "resolve", "network",
                "http", "timed out", "timeout", "getaddrinfo",
            )):
                raise ToolError(
                    "could not download the background-removal model — no internet access"
                ) from None
            raise ToolError("background removal failed — the image may be unsupported") from None
        finally:
            img.close()
        out = ctx.output_dir / f"{src.stem}-nobg.png"
        result.save(out, "PNG")
        result.close()
        if out.stat().st_size == 0:
            raise ToolError("background removal produced no output")
        ctx.progress(1.0, "done")
