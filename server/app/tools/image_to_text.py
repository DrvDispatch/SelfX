"""image-to-text: OCR an image to plain text.

Two engines: EasyOCR (default — 80+ languages, GPU-accelerated, higher accuracy)
and RapidOCR (fast pure-ONNX CPU fallback, PP-OCR models). Both yield rows of
[box, text, score] so the confidence / reading-order handling is shared.
"""

from ._imaging import downscale_max, flatten_rgb, load_image
from .base import Tool, ToolContext, ToolError
from .registry import register

_ENGINE = None  # cached RapidOCR engine
_EASY_READERS: dict[tuple, object] = {}  # cached EasyOCR readers keyed by language set
# Downscale oversized inputs before detection to cut memory / time; large scans
# past this size gain little accuracy and dominate CPU cost.
_MAX_DIM = 1536

# Common EasyOCR language codes the UI advertises (it supports 80+; any valid code
# works). Kept small and CJK-compatible-grouped for the picker.
_EASY_LANGS = ["en", "ch_sim", "ch_tra", "ja", "ko", "fr", "de", "es", "it",
               "pt", "ru", "ar", "hi", "fa", "nl", "tr", "vi", "th"]


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _ENGINE = RapidOCR()
    return _ENGINE


def _easyocr_reader(langs: tuple[str, ...]):
    reader = _EASY_READERS.get(langs)
    if reader is None:
        import easyocr
        import torch
        reader = easyocr.Reader(list(langs), gpu=torch.cuda.is_available())
        _EASY_READERS[langs] = reader
    return reader


def _norm_langs(raw: object) -> tuple[str, ...]:
    """Parse a comma/space separated language string into a validated EasyOCR set.
    EasyOCR requires compatible groups; on an invalid combo we fall back to English."""
    if not raw:
        return ("en",)
    parts = [p.strip() for p in str(raw).replace(",", " ").split() if p.strip()]
    langs = tuple(dict.fromkeys(p for p in parts if p in _EASY_LANGS)) or ("en",)
    return langs


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
            "engine": {
                "type": "string",
                "title": "OCR engine",
                "description": "easyocr = 80+ languages, GPU, higher accuracy; "
                               "rapidocr = fast CPU fallback.",
                "enum": ["easyocr", "rapidocr"],
                "default": "easyocr",
            },
            "languages": {
                "type": "string",
                "title": "Languages (EasyOCR)",
                "description": "Comma-separated codes, e.g. 'en' or 'en,ch_sim'. "
                               "Codes: " + ", ".join(_EASY_LANGS),
                "default": "en",
                "maxLength": 60,
            },
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
        for mod in ("easyocr", "rapidocr_onnxruntime"):
            try:
                __import__(mod)
                return True, None
            except Exception:
                continue
        return False, "no OCR engine (EasyOCR / RapidOCR) is installed"

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
        engine = str(ctx.params.get("engine", "easyocr")).lower()
        langs = _norm_langs(ctx.params.get("languages", "en"))

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
        # Pick the engine; fall back to RapidOCR if EasyOCR isn't importable so the
        # tool keeps working. Both branches build rows of [box, text, score].
        want_easy = engine == "easyocr"
        try:
            import easyocr  # noqa: F401
            has_easy = True
        except Exception:
            has_easy = False
        rows: list = []
        if want_easy and has_easy:
            try:
                reader = _easyocr_reader(langs)
                rot = [90, 180, 270] if detect_rotation else None
                raw = reader.readtext(ocr_input, detail=1, paragraph=False, rotation_info=rot)
                rows = [[box, text, float(conf)] for (box, text, conf) in raw]
            except Exception:
                raise ToolError("OCR failed — the file may not be a readable image") from None
        else:
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
