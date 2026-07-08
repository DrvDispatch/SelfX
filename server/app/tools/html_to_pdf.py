"""html-to-pdf: render a self-contained HTML file to PDF with WeasyPrint (no browser)."""

from ._docutil import validate_pdf_output
from .base import Tool, ToolContext, ToolError
from .registry import register

_PAGE_SIZES = ["", "A4", "A3", "A5", "Letter", "Legal"]
_PDF_VARIANTS = ["", "pdf/a-2b", "pdf/a-3b", "pdf/ua-1"]


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
    params_schema = {
        "type": "object",
        "properties": {
            "landscape": {
                "type": "boolean",
                "title": "Landscape",
                "description": "Produce the PDF in landscape orientation.",
                "default": False,
            },
            "page_size": {
                "type": "string",
                "title": "Page size",
                "description": "Override the page size (blank = use the HTML's own @page/default).",
                "enum": _PAGE_SIZES,
                "default": "",
            },
            "margin": {
                "type": "string",
                "title": "Page margin",
                "description": "CSS margin applied to every page, e.g. '20mm' or '1in' (blank = HTML default).",
                "default": "",
            },
            "presentational_hints": {
                "type": "boolean",
                "title": "Honor legacy HTML attributes",
                "description": "Apply presentational HTML attributes (width, align, bgcolor, ...).",
                "default": False,
            },
            "pdf_variant": {
                "type": "string",
                "title": "PDF variant",
                "description": "Archival/accessible output (PDF/A or PDF/UA); requires a recent WeasyPrint.",
                "enum": _PDF_VARIANTS,
                "default": "",
            },
        },
    }

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

        # Decode with charset detection so legacy-encoded / charset-less fragments
        # don't mojibake. UTF-8 files take the byte-identical fast path (filename=).
        html_kwargs = self._html_source(src)

        page_css = self._page_css(ctx)
        stylesheets = None
        if page_css is not None:
            from weasyprint import CSS

            stylesheets = [CSS(string=page_css)]

        write_kwargs: dict = {}
        if bool(ctx.params.get("presentational_hints", False)):
            write_kwargs["presentational_hints"] = True
        if stylesheets is not None:
            write_kwargs["stylesheets"] = stylesheets
        variant = str(ctx.params.get("pdf_variant", "") or "").strip()
        if variant and variant in _PDF_VARIANTS and variant != "":
            write_kwargs["pdf_variant"] = variant

        try:
            doc = HTML(url_fetcher=_safe_url_fetcher, **html_kwargs)
            try:
                doc.write_pdf(str(out), **write_kwargs)
            except TypeError:
                # Older WeasyPrint lacks pdf_variant (and possibly other kwargs);
                # retry without the version-specific option rather than failing.
                write_kwargs.pop("pdf_variant", None)
                doc.write_pdf(str(out), **write_kwargs)
        except ToolError:
            raise
        except Exception:
            raise ToolError(
                "could not render this HTML — the file may be malformed "
                "(note: external and remote resources are not fetched; embed them as data: URIs)"
            ) from None
        # Validate SEMANTIC output: a real PDF with >= 1 page, not just size > 0.
        validate_pdf_output(out, min_pages=1)
        ctx.progress(1.0, "done")

    def _html_source(self, src) -> dict:
        """Return HTML() kwargs: filename= for UTF-8, string=<decoded> otherwise."""
        try:
            data = src.read_bytes()
        except Exception:
            return {"filename": str(src)}
        try:
            data.decode("utf-8")
            return {"filename": str(src)}
        except UnicodeDecodeError:
            pass
        try:
            from charset_normalizer import from_bytes

            best = from_bytes(data).best()
            if best is not None:
                return {"string": str(best), "base_url": str(src)}
        except Exception:
            pass
        return {"filename": str(src)}

    def _page_css(self, ctx: ToolContext) -> str | None:
        """Build an @page rule from the geometry params, or None if none are set."""
        landscape = bool(ctx.params.get("landscape", False))
        size = str(ctx.params.get("page_size", "") or "").strip()
        if size not in _PAGE_SIZES:
            size = ""
        margin = str(ctx.params.get("margin", "") or "").strip()

        if not landscape and not size and not margin:
            return None

        decls = []
        size_val = " ".join(v for v in (size, "landscape" if landscape else "") if v).strip()
        if size_val:
            decls.append(f"size: {size_val};")
        if margin:
            # Keep it to a safe CSS length token set; reject anything with braces.
            if "{" in margin or "}" in margin or ";" in margin:
                raise ToolError("invalid margin value")
            decls.append(f"margin: {margin};")
        if not decls:
            return None
        return "@page { " + " ".join(decls) + " }"
