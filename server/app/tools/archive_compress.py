"""archive-compress: bundle uploaded files into a zip or 7z archive (SPEC §8)."""

import zipfile

from .base import Tool, ToolContext, ToolError
from .registry import register

# Extensions whose bytes are already compressed: DEFLATE gains ~nothing on them
# while costing real CPU and a double read, so these members are stored verbatim
# (ZIP_STORED). Everything else stays ZIP_DEFLATED.
_ALREADY_COMPRESSED = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".avif",
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v",
    ".mp3", ".aac", ".m4a", ".ogg", ".oga", ".opus", ".flac",
    ".zip", ".7z", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".rar",
    ".pdf", ".docx", ".xlsx", ".pptx",
}


@register
class ArchiveCompress(Tool):
    slug = "archive-compress"
    name = "Compress files"
    category = "utilities"
    description = "Bundle one or more files into a single .zip or .7z archive."
    accepts = []  # any file type is acceptable input
    multi_file = True
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "title": "Format",
                "enum": ["zip", "7z"],
                "default": "zip",
            }
        },
    }

    def run(self, ctx: ToolContext) -> None:
        fmt = str(ctx.params.get("format", "zip"))
        total = len(ctx.input_paths)
        if fmt == "zip":
            out_path = ctx.output_dir / "archive.zip"
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, path in enumerate(ctx.input_paths):
                    ctx.progress(i / total, f"adding {path.name}")
                    compress = (
                        zipfile.ZIP_STORED
                        if path.suffix.lower() in _ALREADY_COMPRESSED
                        else zipfile.ZIP_DEFLATED
                    )
                    zf.write(path, arcname=path.name, compress_type=compress)
        elif fmt == "7z":
            try:
                import py7zr
            except Exception:
                raise ToolError("the 7z engine is not available on this server") from None
            out_path = ctx.output_dir / "archive.7z"
            with py7zr.SevenZipFile(out_path, "w") as zf:
                for i, path in enumerate(ctx.input_paths):
                    ctx.progress(i / total, f"adding {path.name}")
                    zf.write(path, arcname=path.name)
        else:
            raise ToolError(f"unsupported archive format '{fmt}'")
        ctx.progress(1.0, f"created {out_path.name}")
