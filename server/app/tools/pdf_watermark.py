"""pdf-watermark: stamp diagonal text across every page of a PDF."""

import io
import math
import os

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .base import Tool, ToolContext, ToolError
from .pdf_split import _parse_pages
from .registry import register

_FONT_NAME: str | None = None

# Named colours -> (r, g, b) in 0..1. #RRGGBB hex is also accepted at run time.
_COLORS = {
    "gray": (0.5, 0.5, 0.5),
    "grey": (0.5, 0.5, 0.5),
    "black": (0.0, 0.0, 0.0),
    "red": (0.8, 0.0, 0.0),
    "blue": (0.0, 0.0, 0.8),
    "green": (0.0, 0.5, 0.0),
}


def _parse_color(value: str) -> tuple[float, float, float]:
    """Parse a named colour or #RRGGBB hex; fall back to gray (the classic default)."""
    s = str(value or "").strip().lower()
    if s in _COLORS:
        return _COLORS[s]
    if s.startswith("#") and len(s) == 7:
        try:
            return (int(s[1:3], 16) / 255, int(s[3:5], 16) / 255, int(s[5:7], 16) / 255)
        except ValueError:
            pass
    return _COLORS["gray"]


def _watermark_font() -> str:
    """Register a bundled Unicode TTF once so CJK/RTL/accented text renders instead of
    tofu (or an encoding error). Falls back to reportlab's built-in Helvetica-Bold."""
    global _FONT_NAME
    if _FONT_NAME is not None:
        return _FONT_NAME
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    # Bitstream Vera ships INSIDE reportlab (always installed here) — covers
    # Latin/Cyrillic/Greek, so it is a reliable "bundled Unicode TTF".
    try:
        import reportlab

        rdir = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
        candidates += [os.path.join(rdir, "VeraBd.ttf"), os.path.join(rdir, "Vera.ttf")]
    except Exception:
        pass
    candidates += ["C:/Windows/Fonts/arialuni.ttf", "C:/Windows/Fonts/arial.ttf"]
    for path in candidates:
        try:
            if os.path.isfile(path):
                pdfmetrics.registerFont(TTFont("SelfXWatermark", path))
                _FONT_NAME = "SelfXWatermark"
                return _FONT_NAME
        except Exception:
            continue
    _FONT_NAME = "Helvetica-Bold"
    return _FONT_NAME


def _overlay(
    width: float,
    height: float,
    text: str,
    font_name: str,
    *,
    angle: float = 45.0,
    extra_rotate: float = 0.0,
    opacity: float = 0.30,
    rgb: tuple[float, float, float] = (0.5, 0.5, 0.5),
    font_size: int = 0,
    tile: bool = False,
) -> bytes:
    """Render the one-page reportlab overlay and return its raw PDF bytes."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    # Auto size (classic formula) unless the caller pinned an explicit size.
    size = font_size if font_size > 0 else max(24, int(min(width, height) / 12))
    r, g, b = rgb
    c.saveState()
    c.translate(width / 2, height / 2)
    # reportlab rotates counter-clockwise; a page's /Rotate is applied clockwise on
    # display, so add it back to keep the stamp diagonal in the viewed orientation.
    c.rotate(angle + extra_rotate)
    c.setFillColor(Color(r, g, b, alpha=opacity))
    c.setFont(font_name, size)
    if tile:
        # Repeat the text across the whole (rotated) plane so no area is left bare.
        text_w = c.stringWidth(text, font_name, size)
        step_x = max(text_w + size * 2.0, size * 4.0)
        step_y = size * 3.0
        reach = math.hypot(width, height) / 2 + max(step_x, step_y)
        y = -reach
        while y <= reach:
            x = -reach
            while x <= reach:
                c.drawCentredString(x, y, text)
                x += step_x
            y += step_y
    else:
        c.drawCentredString(0, 0, text)
    c.restoreState()
    c.save()
    return buf.getvalue()


@register
class PdfWatermark(Tool):
    slug = "pdf-watermark"
    name = "Watermark PDF"
    category = "pdf"
    description = "Stamp semi-transparent diagonal text (e.g. CONFIDENTIAL) across every page."
    accepts = [".pdf"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "title": "Watermark text",
                "minLength": 1,
                "maxLength": 60,
                "default": "CONFIDENTIAL",
            },
            "opacity": {
                "type": "number",
                "title": "Opacity",
                "description": "0 = invisible, 1 = solid.",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.30,
            },
            "color": {
                "type": "string",
                "title": "Colour",
                "description": "gray, black, red, blue, green, or a #RRGGBB hex value.",
                "default": "gray",
                "maxLength": 16,
            },
            "angle": {
                "type": "number",
                "title": "Angle",
                "description": "Rotation of the text in degrees (45 = classic diagonal).",
                "minimum": -360.0,
                "maximum": 360.0,
                "default": 45.0,
            },
            "font_size": {
                "type": "integer",
                "title": "Font size",
                "description": "Point size. 0 = auto-scale to the page.",
                "minimum": 0,
                "maximum": 400,
                "default": 0,
            },
            "tile": {
                "type": "boolean",
                "title": "Repeat across page",
                "description": "Tile the text in a grid instead of a single centred stamp.",
                "default": False,
            },
            "pages": {
                "type": "string",
                "title": "Pages",
                "description": "Which pages to stamp, e.g. 1-3,7 — leave empty for every page.",
                "default": "",
                "maxLength": 200,
            },
            "password": {
                "type": "string",
                "title": "Password",
                "description": "Password to open the input if it is encrypted — leave blank for unprotected PDFs.",
                "default": "",
                "maxLength": 128,
            },
        },
        "required": ["text"],
    }

    def run(self, ctx: ToolContext) -> None:
        text = str(ctx.params.get("text", "CONFIDENTIAL"))
        try:
            opacity = float(ctx.params.get("opacity", 0.30))
        except (TypeError, ValueError):
            opacity = 0.30
        opacity = max(0.0, min(1.0, opacity))
        rgb = _parse_color(ctx.params.get("color", "gray"))
        try:
            angle = float(ctx.params.get("angle", 45.0))
        except (TypeError, ValueError):
            angle = 45.0
        angle = max(-360.0, min(360.0, angle))
        try:
            font_size = int(ctx.params.get("font_size", 0) or 0)
        except (TypeError, ValueError):
            font_size = 0
        font_size = max(0, min(400, font_size))
        tile = bool(ctx.params.get("tile", False))
        spec = str(ctx.params.get("pages", "")).strip()
        password = str(ctx.params.get("password", ""))

        src = ctx.input_paths[0]
        try:
            reader = PdfReader(str(src))
        except Exception:
            raise ToolError("the input is not a valid PDF file") from None
        if reader.is_encrypted:
            if password:
                try:
                    decrypted = reader.decrypt(password)
                except Exception:
                    decrypted = 0
                if not decrypted:
                    raise ToolError("could not decrypt the PDF — the password is wrong")
            else:
                raise ToolError(
                    "the PDF is password-protected — unlock it first, or provide the password"
                )

        writer = PdfWriter()
        font_name = _watermark_font()
        pages = reader.pages
        total = len(pages) or 1
        # Which pages to stamp (0-based); default is every page.
        if spec:
            selected = set(_parse_pages(spec, len(pages)))
        else:
            selected = set(range(len(pages)))
        # Most PDFs have a single page size — cache the rendered overlay BYTES per
        # (w, h, rotate) key so the reportlab canvas runs O(distinct sizes) times, not
        # once per page. A fresh PdfReader page is built per merge to preserve the
        # original per-page semantics (no shared/mutated page object).
        overlay_cache: dict = {}
        kept = 0
        for i, page in enumerate(pages):
            ctx.progress(i / total, f"watermarking page {i + 1}")
            # A single malformed page must not abort the whole document: on failure,
            # keep the page (unstamped) and carry on.
            if i in selected:
                try:
                    w = float(page.mediabox.width)
                    h = float(page.mediabox.height)
                    try:
                        rotate = int(page.rotation or 0) % 360
                    except Exception:
                        rotate = 0
                    key = (round(w, 1), round(h, 1), rotate)
                    overlay_bytes = overlay_cache.get(key)
                    if overlay_bytes is None:
                        overlay_bytes = _overlay(
                            w,
                            h,
                            text,
                            font_name,
                            angle=angle,
                            extra_rotate=rotate,
                            opacity=opacity,
                            rgb=rgb,
                            font_size=font_size,
                            tile=tile,
                        )
                        overlay_cache[key] = overlay_bytes
                    overlay = PdfReader(io.BytesIO(overlay_bytes)).pages[0]
                    page.merge_page(overlay)
                except Exception:
                    pass
            writer.add_page(page)
            kept += 1
        if kept == 0:
            raise ToolError("the PDF has no pages to watermark")
        with (ctx.output_dir / f"{src.stem}-watermarked.pdf").open("wb") as fh:
            writer.write(fh)
        ctx.progress(1.0, "done")
