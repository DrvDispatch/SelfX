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
        # work on a copy inside output_dir; exiftool overwrites it in place
        out_path = ctx.output_dir / src.name
        shutil.copy2(src, out_path)
        ctx.progress(0.4, "stripping metadata")
        ctx.run_cmd(["exiftool", "-all=", "-overwrite_original", str(out_path)])
        if not out_path.is_file():
            raise ToolError("metadata removal produced no output")
        ctx.progress(1.0, "done")
