"""Shared Pillow helpers for the image tools (SPEC §8).

Every image adapter routes its input through :func:`load_image` so that a single
place handles:

* EXIF orientation — phone photos tagged with a rotation are transposed to the
  correct pixels (metadata is stripped downstream, so the rotation must be baked
  into the pixels or the photo comes out sideways).
* Decompression-bomb / pixel guard — a small but highly-compressed PNG or an
  uncompressed BMP/TIFF can decode to multi-GB of RAM and OOM the CPU-only
  worker. We refuse anything whose pixel count exceeds ``_MAX_PIXELS`` with a
  clear message instead of letting Pillow raise an opaque DecompressionBombError
  that the callers used to mislabel as "not a readable image".

:func:`flatten_rgb` composites any alpha channel onto a solid background and
returns an RGB image, so transparent regions no longer turn black when the
image is saved to JPEG or embedded in a PDF.
"""

from pathlib import Path

from PIL import Image, ImageOps

from .base import ToolError

try:  # Pillow raises this once a decode exceeds MAX_IMAGE_PIXELS
    from PIL.Image import DecompressionBombError
except Exception:  # pragma: no cover - very old Pillow
    DecompressionBombError = Exception

# Refuse images larger than this many pixels (width * height). 64 MP is roughly
# an 8000x8000 photo — well above any real phone/camera capture but small enough
# to bound peak RAM on the CPU-only worker. Kept below Pillow's own ~89 MP
# default so our friendly check fires first.
_MAX_PIXELS = 64_000_000


def load_image(path) -> Image.Image:
    """Open an image safely: guard pixel count, decode, apply EXIF orientation.

    Raises ``ToolError('this image is too large to process safely')`` for
    decompression bombs / oversized inputs, and a generic readability error for
    anything Pillow cannot decode.
    """
    path = Path(path)
    try:
        img = Image.open(path)
    except DecompressionBombError:
        raise ToolError("this image is too large to process safely") from None
    except Exception:
        raise ToolError("the file is not a readable image") from None

    # Image.open is lazy: the header gives us the dimensions before any pixels
    # are decoded, so we can reject a bomb before allocating its buffer.
    try:
        width, height = img.size
    except Exception:
        img.close()
        raise ToolError("the file is not a readable image") from None
    if width * height > _MAX_PIXELS:
        img.close()
        raise ToolError("this image is too large to process safely")

    try:
        img.load()
    except DecompressionBombError:
        img.close()
        raise ToolError("this image is too large to process safely") from None
    except Exception:
        img.close()
        raise ToolError("the file is not a readable image") from None

    # Bake the EXIF Orientation into the pixels (best-effort — never fatal).
    try:
        transposed = ImageOps.exif_transpose(img)
        if transposed is not None and transposed is not img:
            img.close()
            img = transposed
    except Exception:
        pass
    return img


def flatten_rgb(img: Image.Image, bg=(255, 255, 255)) -> Image.Image:
    """Composite any alpha onto ``bg`` and return an RGB image.

    Prevents transparent regions from turning black when written to JPEG / PDF
    and normalises exotic modes (CMYK, L, I;16, P) to plain RGB.
    """
    if img.mode == "RGB":
        return img
    has_alpha = img.mode in ("RGBA", "LA", "PA") or (
        img.mode == "P" and "transparency" in img.info
    )
    if has_alpha:
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, bg)
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return img.convert("RGB")


def downscale_max(img: Image.Image, max_dim: int) -> Image.Image:
    """Return a copy scaled so its longest side is ``max_dim`` (only if larger).

    Used to cut payload / inference cost before AI vision or OCR. Aspect ratio is
    preserved; images already within the limit are returned unchanged.
    """
    width, height = img.size
    longest = max(width, height)
    if longest <= max_dim or longest == 0:
        return img
    scale = max_dim / longest
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return img.resize(new_size, Image.LANCZOS)
