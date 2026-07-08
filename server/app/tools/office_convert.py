"""office-convert: Office/HTML/Markdown -> PDF (SPEC §8).

Prefers the Gotenberg microservice when it is running (REPORT §2.2); falls back to
a local LibreOffice `soffice` process so the tool works without Docker too.
"""

import json
import shutil

import httpx

from ..config import settings
from ._docutil import validate_pdf_output
from .base import Tool, ToolContext, ToolError
from .registry import register

# Text-like inputs whose bytes we charset-normalize to UTF-8 before conversion.
_TEXT_EXTS = {".txt", ".md", ".html", ".htm"}

# OOXML (ZIP-based) formats. An encrypted OOXML file is an OLE2 compound file that
# does NOT begin with the ZIP local-file magic 'PK', which lets us reject it early
# instead of letting soffice hang until the timeout.
_OOXML_EXTS = {".docx", ".xlsx", ".pptx"}

# soffice PDF export filter per document family (used only when export options are set).
_CALC_EXTS = {".xlsx", ".xls", ".ods", ".csv"}
_IMPRESS_EXTS = {".pptx", ".ppt", ".odp"}


def _soffice_bin() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def _gotenberg_ok() -> bool:
    try:
        r = httpx.get(f"{settings.gotenberg_url}/health", timeout=2.0)
        return r.status_code < 500
    except Exception:
        return False


@register
class OfficeConvert(Tool):
    slug = "office-convert"
    name = "Office / HTML / Markdown to PDF"
    category = "documents"
    description = "Convert Word, Excel, PowerPoint, ODF, HTML, Markdown, RTF or text into a PDF."
    accepts = [".docx", ".doc", ".odt", ".pptx", ".ppt", ".xlsx", ".ods", ".html", ".md", ".txt", ".rtf"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "landscape": {
                "type": "boolean",
                "title": "Landscape",
                "description": "Produce the PDF in landscape orientation",
                "default": False,
            },
            "page_ranges": {
                "type": "string",
                "title": "Page ranges",
                "description": "Export only these pages, e.g. '1-3,5' (blank = all pages).",
                "default": "",
            },
            "pdfa": {
                "type": "boolean",
                "title": "PDF/A archival output",
                "description": "Produce a self-contained PDF/A-2b file suitable for long-term archiving.",
                "default": False,
            },
        },
    }

    def available(self) -> tuple[bool, str | None]:
        if _gotenberg_ok() or _soffice_bin():
            return True, None
        return False, "no document-conversion backend (Gotenberg or LibreOffice) is available"

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        landscape = bool(ctx.params.get("landscape", False))
        page_ranges = self._clean_page_ranges(ctx.params.get("page_ranges", ""))
        pdfa = bool(ctx.params.get("pdfa", False))
        out_path = ctx.output_dir / f"{src.stem}.pdf"

        # Reject password-protected OOXML up front instead of hanging until timeout.
        self._reject_encrypted(src)

        # Normalize legacy-encoded text inputs to a UTF-8 temp copy (same filename,
        # so output naming is unchanged) to avoid mojibake. UTF-8 files are untouched.
        conv_src = self._prepare_source(ctx, src)

        ctx.progress(0.3, "converting to PDF")
        if _gotenberg_ok():
            self._via_gotenberg(conv_src, out_path, landscape, page_ranges, pdfa)
        else:
            self._via_libreoffice(ctx, conv_src, out_path, page_ranges, pdfa)

        # Validate SEMANTIC output: a real PDF with >= 1 page, not just size > 0.
        # LibreOffice/Gotenberg can emit a valid-but-blank PDF from garbage input.
        validate_pdf_output(out_path, min_pages=1)
        ctx.progress(1.0, "saved PDF")

    @staticmethod
    def _clean_page_ranges(value) -> str:
        """Accept only a page-range token like '1-3,5,8-'; reject anything else."""
        s = str(value or "").strip()
        if not s:
            return ""
        allowed = set("0123456789,- ")
        if set(s) - allowed:
            raise ToolError("invalid page ranges — use digits, ranges and commas, e.g. '1-3,5'")
        return s.replace(" ", "")

    @staticmethod
    def _reject_encrypted(src) -> None:
        if src.suffix.lower() not in _OOXML_EXTS:
            return
        try:
            head = src.read_bytes()[:4]
        except Exception:
            return
        # Valid .docx/.xlsx/.pptx are ZIP archives beginning with 'PK'. Anything
        # else (typically the OLE2 'EncryptedPackage' container) is unreadable here.
        if not head.startswith(b"PK"):
            raise ToolError(
                "this Office file appears to be password-protected or corrupt — "
                "remove the password and try again"
            )

    def _prepare_source(self, ctx: ToolContext, src):
        if src.suffix.lower() not in _TEXT_EXTS:
            return src
        try:
            data = src.read_bytes()
        except Exception:
            return src
        try:
            data.decode("utf-8")
            return src  # already UTF-8: leave byte-identical
        except UnicodeDecodeError:
            pass
        try:
            from charset_normalizer import from_bytes

            best = from_bytes(data).best()
            if best is None:
                return src
            tmp = ctx.workdir / src.name  # same filename => same output stem
            tmp.write_text(str(best), encoding="utf-8")
            return tmp
        except Exception:
            return src

    def _via_gotenberg(self, src, out_path, landscape: bool, page_ranges: str, pdfa: bool) -> None:
        data: dict[str, str] = {}
        if landscape:
            data["landscape"] = "true"
        if page_ranges:
            data["nativePageRanges"] = page_ranges
        if pdfa:
            data["pdfa"] = "PDF/A-2b"
        try:
            with src.open("rb") as fh:
                files = {"files": (src.name, fh, "application/octet-stream")}
                r = httpx.post(
                    f"{settings.gotenberg_url}/forms/libreoffice/convert",
                    files=files,
                    data=data,
                    timeout=min(settings.job_timeout_seconds, 600),
                )
        except httpx.HTTPError:
            raise ToolError("could not reach the document-conversion service") from None
        if r.status_code != 200:
            detail = r.text.strip()[:200] if r.text else ""
            raise ToolError(f"conversion failed: {detail or 'the file may be unsupported or corrupt'}")
        out_path.write_bytes(r.content)

    def _via_libreoffice(self, ctx: ToolContext, src, out_path, page_ranges: str, pdfa: bool) -> None:
        soffice = _soffice_bin()
        if not soffice:
            raise ToolError("no document-conversion backend is available")
        # A per-job profile dir avoids the shared-profile lock when jobs run in parallel.
        profile = ctx.workdir / "lo_profile"
        ctx.run_cmd(
            [
                soffice,
                "--headless",
                "--nologo",
                "--nofirststartwizard",
                f"-env:UserInstallation=file://{profile}",
                "--convert-to",
                self._soffice_target(src, page_ranges, pdfa),
                "--outdir",
                str(ctx.output_dir),
                str(src),
            ],
            timeout=min(settings.job_timeout_seconds, 300),
        )
        # soffice writes <input-stem>.pdf into outdir, which equals out_path here.
        produced = ctx.output_dir / f"{src.stem}.pdf"
        if produced != out_path and produced.is_file():
            produced.replace(out_path)

    @staticmethod
    def _soffice_target(src, page_ranges: str, pdfa: bool) -> str:
        """Build the --convert-to value. Plain 'pdf' when no export options are set
        (identical to prior behavior); otherwise an explicit PDF export filter with
        FilterData (LibreOffice 7.4+)."""
        if not page_ranges and not pdfa:
            return "pdf"
        ext = src.suffix.lower()
        if ext in _CALC_EXTS:
            flt = "calc_pdf_Export"
        elif ext in _IMPRESS_EXTS:
            flt = "impress_pdf_Export"
        else:
            flt = "writer_pdf_Export"
        filter_data: dict = {}
        if page_ranges:
            filter_data["PageRange"] = {"type": "string", "value": page_ranges}
        if pdfa:
            # SelectPdfVersion: 1=PDF/A-1b, 2=PDF/A-2b, 3=PDF/A-3b (recent LO).
            filter_data["SelectPdfVersion"] = {"type": "long", "value": 2}
        return f"pdf:{flt}:{json.dumps(filter_data)}"
