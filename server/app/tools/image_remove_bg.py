"""image-remove-bg: remove an image background with rembg. Defaults to BiRefNet
(SOTA matting), with U^2-Net kept as the fast option (CPU/ONNX)."""

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
                "description": (
                    "birefnet-general = best quality (SOTA edges/hair); "
                    "birefnet-portrait = tuned for people; *-lite / u2net = faster"
                ),
                "enum": [
                    "birefnet-general",
                    "birefnet-general-lite",
                    "birefnet-portrait",
                    "isnet-general-use",
                    "u2net",
                    "u2net_human_seg",
                    "u2netp",
                    "silueta",
                ],
                "default": "birefnet-general",
            },
            "alpha_matting": {
                "type": "boolean",
                "title": "Refine edges (alpha matting)",
                "description": "Cleaner hair/fur edges at extra CPU cost",
                "default": False,
            },
            "alpha_matting_foreground_threshold": {
                "type": "integer",
                "title": "Foreground threshold",
                "description": "Alpha-matting foreground cutoff (0-255)",
                "minimum": 0,
                "maximum": 255,
                "default": 240,
            },
            "alpha_matting_background_threshold": {
                "type": "integer",
                "title": "Background threshold",
                "description": "Alpha-matting background cutoff (0-255)",
                "minimum": 0,
                "maximum": 255,
                "default": 10,
            },
            "alpha_matting_erode_size": {
                "type": "integer",
                "title": "Edge erode size",
                "description": "Alpha-matting erosion radius in px",
                "minimum": 0,
                "maximum": 40,
                "default": 10,
            },
            "full_resolution": {
                "type": "boolean",
                "title": "Keep full resolution",
                "description": (
                    "Detect at reduced size for speed but apply the mask to the "
                    "original full-resolution pixels"
                ),
                "default": False,
            },
        },
    }

    def available(self) -> tuple[bool, str | None]:
        try:
            import rembg  # noqa: F401
            return True, None
        except Exception:
            return False, "the background-removal engine (rembg) is not installed"

    def run(self, ctx: ToolContext) -> None:
        from PIL import Image
        from rembg import remove

        def _clamp(val: object, lo: int, hi: int, default: int) -> int:
            try:
                return max(lo, min(hi, int(val)))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return default

        model = str(ctx.params.get("model", "birefnet-general"))
        alpha_matting = bool(ctx.params.get("alpha_matting", False))
        full_res = bool(ctx.params.get("full_resolution", False))
        src = ctx.input_paths[0]
        # EXIF-correct, bomb-guarded load; downscale huge inputs to bound CPU/memory
        orig = load_image(src)
        work = downscale_max(orig, _MAX_DIM)

        remove_kw: dict = {}
        if alpha_matting:
            remove_kw.update(
                alpha_matting=True,
                alpha_matting_foreground_threshold=_clamp(
                    ctx.params.get("alpha_matting_foreground_threshold"), 0, 255, 240
                ),
                alpha_matting_background_threshold=_clamp(
                    ctx.params.get("alpha_matting_background_threshold"), 0, 255, 10
                ),
                alpha_matting_erode_size=_clamp(
                    ctx.params.get("alpha_matting_erode_size"), 0, 40, 10
                ),
            )

        ctx.progress(0.3, "removing background (first run downloads the model)")
        try:
            session = _session(model)
            if full_res and work is not orig:
                # detect at reduced size, then upsample the mask (LANCZOS) and apply
                # it to the original full-resolution pixels so detail is preserved
                mask = remove(work, session=session, only_mask=True, **remove_kw)
                mask = mask.resize(orig.size, Image.LANCZOS)
                result = orig.convert("RGBA")
                result.putalpha(mask)
            else:
                result = remove(work, session=session, **remove_kw)
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
            if work is not orig:
                work.close()
            orig.close()
        out = ctx.output_dir / f"{src.stem}-nobg.png"
        result.save(out, "PNG")
        result.close()
        if out.stat().st_size == 0:
            raise ToolError("background removal produced no output")
        ctx.progress(1.0, "done")
