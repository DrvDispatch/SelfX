"""image-to-text: OCR an image to plain text with RapidOCR (PP-OCR models, CPU/ONNX)."""

from ._imaging import downscale_max, flatten_rgb, load_image
from .base import Tool, ToolContext, ToolError
from .registry import register

_ENGINE = None  # cache the OCR engine across jobs in this worker
# Downscale oversized inputs before detection to cut memory / time; large scans
# past this size gain little accuracy and dominate CPU cost.
_MAX_DIM = 1536


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _ENGINE = RapidOCR()
    return _ENGINE


@register
class ImageToText(Tool):
    slug = "image-to-text"
    name = "Image to text (OCR)"
    category = "documents"
    description = "Read printed text out of an image (photo, screenshot, scan) into a text file."
    accepts = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {"type": "object", "properties": {}}

    def available(self) -> tuple[bool, str | None]:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            return True, None
        except Exception:
            return False, "the OCR engine (RapidOCR) is not installed"

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        # load_image applies the decompression-bomb guard (huge scans OOM the worker)
        img = load_image(src)
        ocr_input = str(src)
        if max(img.size) > _MAX_DIM:
            # re-materialise the downscaled image so the engine still reads a file
            # path (identical code path) but a far smaller one
            small = flatten_rgb(downscale_max(img, _MAX_DIM))
            tmp = ctx.workdir / "ocr_input.jpg"
            small.save(tmp, "JPEG", quality=92)
            small.close()
            ocr_input = str(tmp)
        img.close()
        ctx.progress(0.3, "reading text (first run loads the model)")
        try:
            result, _ = _engine()(ocr_input)
        except Exception:
            raise ToolError("OCR failed — the file may not be a readable image") from None
        lines = [row[1] for row in result] if result else []
        text = "\n".join(lines).strip()
        if not text:
            raise ToolError("no text was detected in the image")
        (ctx.output_dir / f"{src.stem}.txt").write_text(text, encoding="utf-8")
        ctx.progress(1.0, f"read {len(lines)} line(s)")
