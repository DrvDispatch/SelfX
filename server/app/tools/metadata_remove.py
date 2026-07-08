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
    params_schema = {
        "type": "object",
        "properties": {
            "gps_only": {
                "type": "boolean",
                "title": "Remove GPS/location only",
                "description": "Strip just GPS/location tags, keeping other metadata",
                "default": False,
            },
            "keep_icc": {
                "type": "boolean",
                "title": "Keep colour profile",
                "description": "Preserve the ICC colour profile so colours don't shift",
                "default": False,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        out_path = ctx.output_dir / src.name
        gps_only = bool(ctx.params.get("gps_only", False))
        keep_icc = bool(ctx.params.get("keep_icc", False))
        ctx.progress(0.4, "stripping metadata")
        # One pass: exiftool copies src -> out_path with metadata removed, instead of
        # duplicating up to max_upload_mb with shutil.copy2 and then rewriting in
        # place. The freshly written file also carries a new mtime, so the original
        # filesystem modification time is not leaked.
        if gps_only:
            strip_args = ["-gps:all="]
        else:
            strip_args = ["-all="]
        # Re-copy the ICC profile from the source (@) after the wipe so the colour
        # profile survives a full strip (documented exiftool idiom).
        if keep_icc and not gps_only:
            strip_args += ["-tagsfromfile", "@", "-icc_profile:all"]
        try:
            ctx.run_cmd(["exiftool", *strip_args, "-o", str(out_path), str(src)])
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
