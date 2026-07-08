"""image-upscale: 4x AI super-resolution with Real-ESRGAN via spandrel (GPU-gated).

Marked GPU-only: super-resolution is impractically slow on CPU, so availability is
gated on a CUDA device. The code path below runs when a GPU is present.
"""

import os
import urllib.request
from pathlib import Path

from ._imaging import load_image
from .base import Tool, ToolContext, ToolError
from .registry import register

# model key -> (download url, cache filename). All are ESRGAN-family weights that
# spandrel auto-detects and loads. UltraSharp is a community favourite that keeps
# text/edges crisper than the RealESRGAN default.
_WEIGHTS: dict[str, tuple[str, str]] = {
    "realesrgan-x4plus": (
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
        "RealESRGAN_x4plus.pth",
    ),
    "ultrasharp-4x": (
        "https://huggingface.co/uwg/upscaler/resolve/main/ESRGAN/4x-UltraSharp.pth",
        "4x-UltraSharp.pth",
    ),
}
_DEFAULT_MODEL = "realesrgan-x4plus"

# Cache the loaded model per (weights, precision) for the lifetime of the worker so
# a warm worker skips the disk load + CUDA upload on every job.
_MODELS: dict[tuple, object] = {}


def _cache_path(filename: str) -> Path:
    """OS-appropriate cache location for the model weights (Windows/Linux/macOS).

    The previous hard-coded ``/root/.cache/selfx`` only existed on the Linux
    container and broke on the Windows dev host; honour SELFX_CACHE_DIR if set.
    """
    base = os.environ.get("SELFX_CACHE_DIR")
    root = Path(base) if base else Path.home() / ".cache" / "selfx"
    return root / filename


@register
class ImageUpscale(Tool):
    slug = "image-upscale"
    name = "Upscale image (AI)"
    category = "images"
    description = "Increase image resolution 4x with Real-ESRGAN (requires a GPU)."
    accepts = [".jpg", ".jpeg", ".png", ".webp", ".bmp"]
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
                    "realesrgan-x4plus = balanced photo default; "
                    "ultrasharp-4x = crisper edges/text (great for screenshots & art)"
                ),
                "enum": ["realesrgan-x4plus", "ultrasharp-4x"],
                "default": "realesrgan-x4plus",
            },
            "precision": {
                "type": "string",
                "title": "Precision",
                "description": (
                    "half = ~2x less VRAM and faster with negligible quality loss; "
                    "full = maximum fidelity"
                ),
                "enum": ["full", "half"],
                "default": "full",
            },
        },
    }

    def available(self) -> tuple[bool, str | None]:
        try:
            import torch
        except Exception:
            return False, "the AI upscaling engine is not installed"
        if not torch.cuda.is_available():
            return False, "AI upscaling requires a GPU (none detected in this environment)"
        try:
            import spandrel  # noqa: F401
        except Exception:
            return False, "the upscaling engine (spandrel) is not installed"
        return True, None

    def _weights(self, ctx: ToolContext, model_key: str) -> Path:
        url, filename = _WEIGHTS.get(model_key, _WEIGHTS[_DEFAULT_MODEL])
        cache = _cache_path(filename)
        if not cache.is_file():
            cache.parent.mkdir(parents=True, exist_ok=True)
            ctx.progress(0.15, "downloading the upscaling model (one time)")
            try:
                urllib.request.urlretrieve(url, str(cache))
            except Exception:
                raise ToolError("could not download the upscaling model weights") from None
        return cache

    def _model(self, weights: Path, half: bool):
        key = (str(weights), half)
        model = _MODELS.get(key)
        if model is None:
            from spandrel import ModelLoader

            model = ModelLoader().load_from_file(str(weights)).cuda().eval()
            if half:
                model = model.half()
            _MODELS[key] = model
        return model

    def run(self, ctx: ToolContext) -> None:
        import numpy as np
        import torch
        from PIL import Image

        half = str(ctx.params.get("precision", "full")) == "half"
        model_key = str(ctx.params.get("model") or _DEFAULT_MODEL)
        if model_key not in _WEIGHTS:
            model_key = _DEFAULT_MODEL
        weights = self._weights(ctx, model_key)
        model = self._model(weights, half)
        src = ctx.input_paths[0]
        # load_image applies EXIF orientation (phone photos upscale upright) and the
        # decompression-bomb guard; split off any alpha so transparency survives.
        img = load_image(src)
        alpha = None
        if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            alpha = rgba.getchannel("A")
            rgb = rgba.convert("RGB")
        else:
            rgb = img.convert("RGB")

        tensor = torch.from_numpy(np.asarray(rgb)).permute(2, 0, 1).unsqueeze(0).float().div(255)
        if half:
            tensor = tensor.half()
        tensor = tensor.cuda()
        ctx.progress(0.5, "upscaling 4x")
        with torch.no_grad():
            out = model(tensor)
        arr = out.squeeze(0).permute(1, 2, 0).float().clamp(0, 1).mul(255).byte().cpu().numpy()
        result = Image.fromarray(arr)
        if alpha is not None:
            # the model only upscales RGB; scale the alpha to match and reattach
            result = result.convert("RGBA")
            result.putalpha(alpha.resize(result.size, Image.LANCZOS))
        result.save(ctx.output_dir / f"{src.stem}-4x.png")
        ctx.progress(1.0, "done")
