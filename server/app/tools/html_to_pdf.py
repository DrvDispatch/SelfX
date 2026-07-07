"""html-to-pdf: render a self-contained HTML file to PDF with WeasyPrint (no browser)."""

from ._docutil import validate_pdf_output
from .base import Tool, ToolContext, ToolError
from .registry import register


def _safe_url_fetcher(url, *args, **kwargs):
    """A url_fetcher that only resolves inline ``data:`` URIs.

    WeasyPrint's default fetcher resolves ``file://``, ``http(s)://`` and relative
    URLs IN-PROCESS, so an uploaded HTML with ``<img src='file:///etc/passwd'>`` or
    ``http://169.254.169.254/...`` would read local files / hit internal hosts and
    embed or exfiltrate them (SSRF). This tool's contract is "self-contained HTML",
    so we allow only embedded ``data:`` resources and quietly skip everything else
    (returning an empty resource, which drops the element instead of aborting the
    whole render).
    """
    if isinstance(url, str) and url.startswith("data:"):
        from weasyprint.urls import default_url_fetcher

        return default_url_fetcher(url, *args, **kwargs)
    return {"string": b"", "mime_type": "application/octet-stream"}


@register
class HtmlToPdf(Tool):
    slug = "html-to-pdf"
    name = "HTML to PDF"
    category = "documents"
    description = "Render a self-contained HTML file to a print-quality PDF (CSS paged media)."
    accepts = [".html", ".htm"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {"type": "object", "properties": {}}

    def available(self) -> tuple[bool, str | None]:
        try:
            import weasyprint  # noqa: F401
            return True, None
        except Exception:
            return False, "the HTML-to-PDF engine (WeasyPrint) is not installed"

    def run(self, ctx: ToolContext) -> None:
        from weasyprint import HTML

        src = ctx.input_paths[0]
        out = ctx.output_dir / f"{src.stem}.pdf"
        ctx.progress(0.4, "rendering HTML to PDF")
        try:
            HTML(filename=str(src), url_fetcher=_safe_url_fetcher).write_pdf(str(out))
        except Exception:
            raise ToolError(
                "could not render this HTML — the file may be malformed "
                "(note: external and remote resources are not fetched; embed them as data: URIs)"
            ) from None
        # Validate SEMANTIC output: a real PDF with >= 1 page, not just size > 0.
        validate_pdf_output(out, min_pages=1)
        ctx.progress(1.0, "done")
