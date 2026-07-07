"""image-upscale: 4x AI super-resolution with Real-ESRGAN via spandrel (GPU-gated).

Marked GPU-only: super-resolution is impractically slow on CPU, so availability is
gated on a CUDA device. The code path below runs when a GPU is present.
"""

import urllib.request
from pathlib import Path

from .base import Tool, ToolContext, ToolError
from .registry import register

_WEIGHTS_URL = (
    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"
)
_CACHE = Path("/root/.cache/selfx/RealESRGAN_x4plus.pth")


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
    params_schema = {"type": "object", "properties": {}}

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

    def _weights(self, ctx: ToolContext) -> Path:
        if not _CACHE.is_file():
            _CACHE.parent.mkdir(parents=True, exist_ok=True)
            ctx.progress(0.15, "downloading the upscaling model (one time)")
            try:
                urllib.request.urlretrieve(_WEIGHTS_URL, str(_CACHE))
            except Exception:
                raise ToolError("could not download the upscaling model weights") from None
        return _CACHE

    def run(self, ctx: ToolContext) -> None:
        import numpy as np
        import torch
        from PIL import Image
        from spandrel import ModelLoader

        weights = self._weights(ctx)
        model = ModelLoader().load_from_file(str(weights)).cuda().eval()
        src = ctx.input_paths[0]
        img = Image.open(src).convert("RGB")
        tensor = (
            torch.from_numpy(np.asarray(img)).permute(2, 0, 1).unsqueeze(0).float().div(255).cuda()
        )
        ctx.progress(0.5, "upscaling 4x")
        with torch.no_grad():
            out = model(tensor)
        arr = out.squeeze(0).permute(1, 2, 0).clamp(0, 1).mul(255).byte().cpu().numpy()
        Image.fromarray(arr).save(ctx.output_dir / f"{src.stem}-4x.png")
        ctx.progress(1.0, "done")
