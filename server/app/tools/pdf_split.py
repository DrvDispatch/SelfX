"""pdf-split: extract a page range, or burst every page into a zip (SPEC §8)."""

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
            try:
                start, end = int(a), int(b)
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
                "description": "e.g. 1-3,7 — leave empty to split every page into a separate PDF",
                "default": "",
                "maxLength": 200,
            }
        },
    }

    def run(self, ctx: ToolContext) -> None:
        spec = str(ctx.params.get("pages", "")).strip()
        try:
            src = pikepdf.open(ctx.input_paths[0])
        except pikepdf.PasswordError:
            raise ToolError("the PDF is password-protected — remove the password first") from None
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
                    out.save(ctx.output_dir / "split.pdf")
                finally:
                    out.close()
                ctx.progress(1.0, "saved split.pdf")
            else:
                zip_path = ctx.output_dir / "pages.zip"
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for i in range(total):
                        ctx.progress(i / total, f"page {i + 1} of {total}")
                        one = pikepdf.new()
                        try:
                            one.pages.append(src.pages[i])
                            page_path = ctx.workdir / f"page_{i + 1:04d}.pdf"
                            one.save(page_path)
                        finally:
                            one.close()
                        zf.write(page_path, arcname=page_path.name)
                        page_path.unlink(missing_ok=True)
                ctx.progress(1.0, f"burst {total} pages into pages.zip")
        finally:
            src.close()
