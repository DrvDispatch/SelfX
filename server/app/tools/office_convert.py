"""office-convert: Office/HTML/Markdown -> PDF (SPEC §8).

Prefers the Gotenberg microservice when it is running (REPORT §2.2); falls back to
a local LibreOffice `soffice` process so the tool works without Docker too.
"""

import shutil

import httpx

from ..config import settings
from ._docutil import validate_pdf_output
from .base import Tool, ToolContext, ToolError
from .registry import register


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
            }
        },
    }

    def available(self) -> tuple[bool, str | None]:
        if _gotenberg_ok() or _soffice_bin():
            return True, None
        return False, "no document-conversion backend (Gotenberg or LibreOffice) is available"

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        landscape = bool(ctx.params.get("landscape", False))
        out_path = ctx.output_dir / f"{src.stem}.pdf"
        ctx.progress(0.3, "converting to PDF")

        if _gotenberg_ok():
            self._via_gotenberg(src, out_path, landscape)
        else:
            self._via_libreoffice(ctx, src, out_path)

        # Validate SEMANTIC output: a real PDF with >= 1 page, not just size > 0.
        # LibreOffice/Gotenberg can emit a valid-but-blank PDF from garbage input.
        validate_pdf_output(out_path, min_pages=1)
        ctx.progress(1.0, "saved PDF")

    def _via_gotenberg(self, src, out_path, landscape: bool) -> None:
        data = {"landscape": "true"} if landscape else {}
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

    def _via_libreoffice(self, ctx: ToolContext, src, out_path) -> None:
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
                "pdf",
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
