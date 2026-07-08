"""archive-compress: bundle uploaded files into a zip, 7z or tar archive (SPEC §8)."""

import shutil
import tarfile
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

_FORMATS = ["zip", "7z", "tar.gz", "tar.xz"]
_LEVELS = ["store", "fast", "normal", "max"]
# Deterministic timestamp for reproducible archives: 1980-01-01 (the zip epoch).
_REPRO_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
_REPRO_MTIME = 315532800  # 1980-01-01 00:00:00 UTC


def _zip_compresslevel(level: str) -> int | None:
    # None => zlib default (level 6); preserves the historical output for 'normal'.
    return {"fast": 1, "normal": None, "max": 9, "store": None}[level]


@register
class ArchiveCompress(Tool):
    slug = "archive-compress"
    name = "Compress files"
    category = "utilities"
    description = "Bundle one or more files into a single .zip, .7z or .tar.gz/.tar.xz archive."
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
                "enum": _FORMATS,
                "default": "zip",
            },
            "level": {
                "type": "string",
                "title": "Compression",
                "description": (
                    "store = no compression (fastest); fast = quick, larger; "
                    "normal = balanced (default); max = smallest, slowest."
                ),
                "enum": _LEVELS,
                "default": "normal",
            },
            "reproducible": {
                "type": "boolean",
                "title": "Reproducible output",
                "description": (
                    "Zero out file timestamps so identical inputs produce a "
                    "byte-identical archive (stable checksums)."
                ),
                "default": False,
            },
            "password": {
                "type": "string",
                "title": "Password (7z only)",
                "description": "Encrypt the archive with AES-256. Applies to the 7z format only.",
                "maxLength": 128,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        fmt = str(ctx.params.get("format", "zip"))
        if fmt not in _FORMATS:
            raise ToolError(f"unsupported archive format '{fmt}'")
        level = str(ctx.params.get("level", "normal"))
        if level not in _LEVELS:
            level = "normal"
        reproducible = bool(ctx.params.get("reproducible", False))
        password = str(ctx.params.get("password", "") or "")

        if fmt == "zip":
            out_path = self._make_zip(ctx, level, reproducible)
        elif fmt == "7z":
            out_path = self._make_7z(ctx, level, password)
        else:  # tar.gz / tar.xz
            out_path = self._make_tar(ctx, fmt, level, reproducible)
        ctx.progress(1.0, f"created {out_path.name}")

    def _make_zip(self, ctx: ToolContext, level: str, reproducible: bool):
        out_path = ctx.output_dir / "archive.zip"
        total = len(ctx.input_paths)
        complevel = _zip_compresslevel(level)
        with zipfile.ZipFile(
            out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=complevel
        ) as zf:
            for i, path in enumerate(ctx.input_paths):
                ctx.progress(i / total, f"adding {path.name}")
                if level == "store":
                    compress = zipfile.ZIP_STORED
                else:
                    compress = (
                        zipfile.ZIP_STORED
                        if path.suffix.lower() in _ALREADY_COMPRESSED
                        else zipfile.ZIP_DEFLATED
                    )
                if reproducible:
                    zinfo = zipfile.ZipInfo(path.name, date_time=_REPRO_ZIP_DATE)
                    zinfo.compress_type = compress
                    zinfo.external_attr = 0o644 << 16
                    # _compresslevel is the per-member level ZipFile.open honors.
                    zinfo._compresslevel = complevel
                    with zf.open(zinfo, "w") as dest, path.open("rb") as srcf:
                        shutil.copyfileobj(srcf, dest, length=1024 * 64)
                else:
                    zf.write(path, arcname=path.name, compress_type=compress,
                             compresslevel=complevel)
        return out_path

    def _make_7z(self, ctx: ToolContext, level: str, password: str):
        try:
            import py7zr
        except Exception:
            raise ToolError("the 7z engine is not available on this server") from None
        out_path = ctx.output_dir / "archive.7z"
        total = len(ctx.input_paths)
        # Only override py7zr's default filters for non-'normal' levels so the
        # historical LZMA2 output is preserved by default.
        filters = None
        if level == "store":
            filters = [{"id": py7zr.FILTER_COPY}]
        elif level == "fast":
            filters = [{"id": py7zr.FILTER_LZMA2, "preset": 1}]
        elif level == "max":
            filters = [{"id": py7zr.FILTER_LZMA2, "preset": 9}]
        kwargs: dict = {}
        if filters is not None:
            kwargs["filters"] = filters
        if password:
            kwargs["password"] = password
            kwargs["header_encryption"] = True
        try:
            with py7zr.SevenZipFile(out_path, "w", **kwargs) as zf:
                for i, path in enumerate(ctx.input_paths):
                    ctx.progress(i / total, f"adding {path.name}")
                    zf.write(path, arcname=path.name)
        except Exception as exc:
            raise ToolError(f"7z compression failed: {exc}") from None
        return out_path

    def _make_tar(self, ctx: ToolContext, fmt: str, level: str, reproducible: bool):
        suffix = "gz" if fmt == "tar.gz" else "xz"
        out_path = ctx.output_dir / f"archive.{fmt}"
        total = len(ctx.input_paths)
        level_map = {"store": 0, "fast": 1, "normal": 6, "max": 9}
        lvl = level_map[level]

        def _repro(ti: "tarfile.TarInfo") -> "tarfile.TarInfo":
            ti.mtime = _REPRO_MTIME
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            return ti

        filt = _repro if reproducible else None
        if suffix == "gz":
            tf = tarfile.open(out_path, "w:gz", compresslevel=lvl)
        else:
            tf = tarfile.open(out_path, "w:xz", preset=lvl)
        with tf:
            for i, path in enumerate(ctx.input_paths):
                ctx.progress(i / total, f"adding {path.name}")
                tf.add(str(path), arcname=path.name, filter=filt)
        return out_path
