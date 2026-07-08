"""pdf-extract-text: pull the text layer out of a PDF into a .txt file."""

from pypdf import PdfReader

from .base import Tool, ToolContext, ToolError
from .pdf_split import _parse_pages
from .registry import register


@register
class PdfExtractText(Tool):
    slug = "pdf-extract-text"
    name = "Extract text from PDF"
    category = "pdf"
    description = "Extract the text layer of a PDF to a plain-text file (scanned PDFs need OCR first)."
    accepts = [".pdf"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "title": "Extraction mode",
                "description": "plain = fast flowing text; layout = preserve columns/tables by keeping spacing.",
                "enum": ["plain", "layout"],
                "default": "plain",
            },
            "pages": {
                "type": "string",
                "title": "Pages",
                "description": "Which pages to extract, e.g. 1-3,7 (open-ended '5-' or '-3' also work) — leave empty for the whole document.",
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
    }

    def run(self, ctx: ToolContext) -> None:
        mode = str(ctx.params.get("mode", "plain")).lower()
        if mode not in ("plain", "layout"):
            mode = "plain"
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

        total = len(reader.pages) or 1
        # Select which page indices to read; default is every page, in order.
        if spec:
            indices = _parse_pages(spec, len(reader.pages))
        else:
            indices = list(range(len(reader.pages)))

        # pypdf's "layout" extraction_mode keeps columns/tables readable; "plain"
        # (the default) flows text and is faster.
        extract_kwargs = {"extraction_mode": "layout"} if mode == "layout" else {}

        parts = []
        for step, i in enumerate(indices):
            ctx.progress(step / total, f"reading page {i + 1}")
            page = reader.pages[i]
            # One malformed page must not abort the whole document — skip it.
            try:
                parts.append(page.extract_text(**extract_kwargs) or "")
            except Exception:
                parts.append("")
        text = "\n\n".join(parts).strip()
        if not text:
            raise ToolError("no text found — this PDF may be scanned; run OCR first")
        (ctx.output_dir / f"{src.stem}.txt").write_text(text, encoding="utf-8")
        ctx.progress(1.0, "done")
