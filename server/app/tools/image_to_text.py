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


def _row_sort_key(row):
    """Sort key for reading order: top-to-bottom (banded), then left-to-right.

    ``row[0]`` is the detection box (4 [x, y] corner points). We band the top y to
    a coarse grid so words on the same visual line stay together before ordering by
    x, which keeps multi-word lines from being scrambled by tiny y differences.
    """
    try:
        box = row[0]
        ys = [float(p[1]) for p in box]
        xs = [float(p[0]) for p in box]
        top, left = min(ys), min(xs)
    except (IndexError, TypeError, ValueError):
        return (0.0, 0.0)
    return (round(top / 10.0), left)


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
    params_schema = {
        "type": "object",
        "properties": {
            "max_dim": {
                "type": "integer",
                "title": "Detection size cap (px)",
                "description": (
                    "Longest side the image is scaled to before OCR. Raise for dense "
                    "scans with small text; lower for speed."
                ),
                "minimum": 512,
                "maximum": 6000,
                "default": _MAX_DIM,
            },
            "min_confidence": {
                "type": "number",
                "title": "Minimum confidence",
                "description": "Drop detected lines below this score (0-1); 0 keeps everything",
                "minimum": 0,
                "maximum": 1,
                "default": 0,
            },
            "detect_rotation": {
                "type": "boolean",
                "title": "Detect rotated text",
                "description": "Enable angle classification for sideways/upside-down lines",
                "default": False,
            },
            "reading_order": {
                "type": "boolean",
                "title": "Sort into reading order",
                "description": "Reorder detected lines top-to-bottom, left-to-right",
                "default": False,
            },
        },
    }

    def available(self) -> tuple[bool, str | None]:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            return True, None
        except Exception:
            return False, "the OCR engine (RapidOCR) is not installed"

    def run(self, ctx: ToolContext) -> None:
        try:
            max_dim = max(512, min(6000, int(ctx.params.get("max_dim", _MAX_DIM))))
        except (TypeError, ValueError):
            max_dim = _MAX_DIM
        try:
            min_conf = max(0.0, min(1.0, float(ctx.params.get("min_confidence", 0))))
        except (TypeError, ValueError):
            min_conf = 0.0
        detect_rotation = bool(ctx.params.get("detect_rotation", False))
        reading_order = bool(ctx.params.get("reading_order", False))

        src = ctx.input_paths[0]
        # load_image applies the decompression-bomb guard (huge scans OOM the worker)
        img = load_image(src)
        ocr_input = str(src)
        if max(img.size) > max_dim:
            # re-materialise the downscaled image so the engine still reads a file
            # path (identical code path) but a far smaller one
            small = flatten_rgb(downscale_max(img, max_dim))
            tmp = ctx.workdir / "ocr_input.jpg"
            small.save(tmp, "JPEG", quality=92)
            small.close()
            ocr_input = str(tmp)
        img.close()
        ctx.progress(0.3, "reading text (first run loads the model)")
        call_kw: dict = {}
        if detect_rotation:
            call_kw["use_cls"] = True
        try:
            result, _ = _engine()(ocr_input, **call_kw)
        except Exception:
            raise ToolError("OCR failed — the file may not be a readable image") from None

        rows = list(result) if result else []
        if min_conf > 0:
            kept = []
            for row in rows:
                try:
                    score = float(row[2])
                except (IndexError, TypeError, ValueError):
                    score = 1.0
                if score >= min_conf:
                    kept.append(row)
            rows = kept
        if reading_order:
            rows = sorted(rows, key=_row_sort_key)

        lines = [row[1] for row in rows]
        text = "\n".join(lines).strip()
        if not text:
            raise ToolError("no text was detected in the image")
        (ctx.output_dir / f"{src.stem}.txt").write_text(text, encoding="utf-8")
        ctx.progress(1.0, f"read {len(lines)} line(s)")
