"""image-to-text: OCR an image to plain text with RapidOCR (PP-OCR models, CPU/ONNX)."""

from .base import Tool, ToolContext, ToolError
from .registry import register

_ENGINE = None  # cache the OCR engine across jobs in this worker


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
        ctx.progress(0.3, "reading text (first run loads the model)")
        try:
            result, _ = _engine()(str(src))
        except Exception:
            raise ToolError("OCR failed — the file may not be a readable image") from None
        lines = [row[1] for row in result] if result else []
        text = "\n".join(lines).strip()
        if not text:
            raise ToolError("no text was detected in the image")
        (ctx.output_dir / f"{src.stem}.txt").write_text(text, encoding="utf-8")
        ctx.progress(1.0, f"read {len(lines)} line(s)")
