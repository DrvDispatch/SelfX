"""metadata-remove: strip EXIF/IPTC/XMP and document metadata with ExifTool (SPEC §8)."""

import shutil

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class MetadataRemove(Tool):
    slug = "metadata-remove"
    name = "Remove metadata"
    category = "utilities"
    description = "Strip EXIF, IPTC, XMP and document metadata from an image, PDF or Office file."
    accepts = [
        ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".heic", ".heif", ".gif",
        ".pdf", ".docx", ".xlsx", ".pptx",
    ]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {"type": "object", "properties": {}}

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        out_path = ctx.output_dir / src.name
        ctx.progress(0.4, "stripping metadata")
        # One pass: exiftool copies src -> out_path with all metadata removed,
        # instead of duplicating up to max_upload_mb with shutil.copy2 and then
        # rewriting in place. The freshly written file also carries a new mtime,
        # so the original filesystem modification time is not leaked.
        try:
            ctx.run_cmd(["exiftool", "-all=", "-o", str(out_path), str(src)])
        except ToolError:
            if src.suffix.lower() in (".heic", ".heif"):
                raise ToolError(
                    "this HEIC/HEIF file could not be rewritten — the installed "
                    "ExifTool build may be read-only for this format"
                ) from None
            raise
        if not out_path.is_file():
            # exiftool emits no output file when there was nothing to strip; the
            # file is already metadata-free, so hand it back unchanged.
            shutil.copy2(src, out_path)
        if not out_path.is_file():
            raise ToolError("metadata removal produced no output")
        ctx.progress(1.0, "done")
