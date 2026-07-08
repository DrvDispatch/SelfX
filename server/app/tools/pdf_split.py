"""pdf-split: extract a page range, or burst every page into a zip (SPEC §8)."""

import io
import zipfile

import pikepdf

from .base import Tool, ToolContext, ToolError
from .registry import register


def _parse_pages(spec: str, total: int) -> list[int]:
    """Parse a 1-based page spec like '1-3,7' into a sorted list of 0-based indices."""
    pages: list[int] = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            # Open-ended ranges: '5-' means page 5 to the end, '-3' means start to page 3.
            try:
                start = int(a) if a else 1
                end = int(b) if b else total
            except ValueError:
                raise ToolError(f"invalid page range '{part}'") from None
        else:
            try:
                start = end = int(part)
            except ValueError:
                raise ToolError(f"invalid page number '{part}'") from None
        if start < 1 or end < 1 or start > end:
            raise ToolError(f"invalid page range '{part}'")
        for n in range(start, end + 1):
            if n > total:
                raise ToolError(f"page {n} is out of range (document has {total} pages)")
            if (n - 1) not in pages:
                pages.append(n - 1)
    return pages


@register
class PdfSplit(Tool):
    slug = "pdf-split"
    name = "Split PDF"
    category = "pdf"
    description = (
        "Extract specific pages (e.g. '1-3,7'), or leave blank to burst every "
        "page into its own PDF returned as a zip."
    )
    accepts = [".pdf"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "pages": {
                "type": "string",
                "title": "Pages",
                "description": "e.g. 1-3,7 (open-ended '5-' or '-3' also work) — leave empty to split every page into a separate PDF",
                "default": "",
                "maxLength": 200,
            },
            "chunk_size": {
                "type": "integer",
                "title": "Pages per file (burst mode)",
                "description": "When bursting (no page spec), group this many pages into each output PDF. 0 or 1 = one page per file.",
                "default": 0,
                "minimum": 0,
                "maximum": 10000,
            },
            "password": {
                "type": "string",
                "title": "Password",
                "description": "Password to open the input if it is encrypted — leave blank for unprotected PDFs.",
                "default": "",
                "maxLength": 128,
            },
            "linearize": {
                "type": "boolean",
                "title": "Optimize for web (linearize)",
                "description": "Linearize the extracted range (range mode only) for fast web view.",
                "default": False,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        spec = str(ctx.params.get("pages", "")).strip()
        password = str(ctx.params.get("password", ""))
        linearize = bool(ctx.params.get("linearize", False))
        try:
            chunk_size = int(ctx.params.get("chunk_size", 0) or 0)
        except (TypeError, ValueError):
            chunk_size = 0
        if chunk_size < 0:
            chunk_size = 0
        try:
            src = pikepdf.open(ctx.input_paths[0], password=password)
        except pikepdf.PasswordError:
            raise ToolError(
                "the PDF is password-protected — provide the password or remove it first"
            ) from None
        except pikepdf.PdfError:
            raise ToolError("the input is not a valid PDF file") from None
        try:
            total = len(src.pages)
            if total == 0:
                raise ToolError("the PDF has no pages")
            if spec:
                indices = _parse_pages(spec, total)
                ctx.progress(0.4, f"extracting {len(indices)} page(s)")
                out = pikepdf.new()
                try:
                    for i in indices:
                        out.pages.append(src.pages[i])
                    save_kwargs = {"linearize": True} if linearize else {}
                    out.save(ctx.output_dir / "split.pdf", **save_kwargs)
                finally:
                    out.close()
                ctx.progress(1.0, "saved split.pdf")
            else:
                zip_path = ctx.output_dir / "pages.zip"
                # Burst mode: serialize each PDF chunk into memory and store it
                # uncompressed (ZIP_STORED). PDF page streams are already compressed,
                # so DEFLATE + per-page temp files only waste CPU and double the I/O.
                # chunk_size groups multiple pages per output file (default: one each).
                step = chunk_size if chunk_size > 1 else 1
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
                    for start in range(0, total, step):
                        end = min(start + step, total)
                        ctx.progress(start / total, f"pages {start + 1}-{end} of {total}")
                        one = pikepdf.new()
                        buf = io.BytesIO()
                        try:
                            for i in range(start, end):
                                one.pages.append(src.pages[i])
                            one.save(buf)
                        finally:
                            one.close()
                        if step == 1:
                            name = f"page_{start + 1:04d}.pdf"
                        else:
                            name = f"pages_{start + 1:04d}-{end:04d}.pdf"
                        zf.writestr(name, buf.getvalue())
                ctx.progress(1.0, f"burst {total} pages into pages.zip")
        finally:
            src.close()
