"""Build a PDF from a page selection in the requested order."""

from typing import ClassVar

import pikepdf

from ._media import guard_output_size
from .base import Tool, ToolContext, ToolError
from .pdf_split import _parse_pages
from .registry import register

_MAX_PAGES = 1000


@register
class PdfOrganize(Tool):
    slug = "pdf-organize"
    name = "Organize PDF pages"
    category = "pdf"
    description = "Choose which pages to keep, reorder them, or remove unwanted pages."
    accepts: ClassVar[list[str]] = [".pdf"]
    params_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "page_order": {
                "type": "string",
                "title": "Pages in output order",
                "description": "For example, 3,1-2 puts page 3 first. Leave blank to keep the current order.",
                "default": "",
                "maxLength": 2000,
            },
            "remove_pages": {
                "type": "string",
                "title": "Remove original pages",
                "description": "For example, 2,5-7 removes those pages using their original numbers.",
                "default": "",
                "maxLength": 2000,
            },
        },
        "additionalProperties": False,
    }

    def run(self, ctx: ToolContext) -> None:
        source = ctx.input_paths[0]
        page_order = ctx.params.get("page_order", "").strip()
        remove_pages = ctx.params.get("remove_pages", "").strip()
        if not page_order and not remove_pages:
            raise ToolError("Choose pages to reorder or remove")

        pending = ctx.workdir / "organized.pdf"
        try:
            with pikepdf.open(source) as pdf:
                if pdf.is_encrypted:
                    raise ToolError("Use Unlock PDF before organizing a protected document")
                total = len(pdf.pages)
                if total < 1 or total > _MAX_PAGES:
                    raise ToolError(f"Choose a PDF with 1 to {_MAX_PAGES} pages")
                selected = _parse_pages(page_order, total) if page_order else list(range(total))
                omitted = set(_parse_pages(remove_pages, total)) if remove_pages else set()
                selected = [index for index in selected if index not in omitted]
                if not selected:
                    raise ToolError("Keep at least one page in the output")
                if selected == list(range(total)):
                    raise ToolError("The page selection leaves the PDF unchanged")

                ctx.progress(0.35, f"Arranging {len(selected)} pages")
                if len(selected) < total:
                    # A new document keeps the selection separate from document-level
                    # structures such as outlines and custom labels in the original.
                    with pikepdf.new() as subset:
                        subset.pages.extend(pdf.pages[index] for index in selected)
                        subset.save(pending)
                else:
                    # Detach before reinserting so page references keep their identity.
                    ordered = [pdf.pages[index] for index in selected]
                    del pdf.pages[:]
                    pdf.pages.extend(ordered)
                    if "/PageLabels" in pdf.Root:
                        del pdf.Root["/PageLabels"]
                    pdf.save(pending)
        except pikepdf.PasswordError:
            raise ToolError("Use Unlock PDF before organizing a protected document") from None
        except pikepdf.PdfError:
            raise ToolError("This PDF could not be organized. Check that it opens in a PDF reader.") from None

        guard_output_size(pending, "organized PDF")
        pending.replace(ctx.output_dir / f"{source.stem}-organized.pdf")
        ctx.progress(1, f"Saved {len(selected)} pages")
