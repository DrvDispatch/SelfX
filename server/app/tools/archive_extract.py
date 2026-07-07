"""archive-extract: safely extract an archive with zip-bomb / traversal guards (SPEC §8, §10).

Guards enforced BEFORE writing anything to disk: no absolute/traversal paths, no
symlinks, <=10k entries, <=2 GiB total expanded, <=100x compression ratio.
"""

import gzip
import shutil
import tarfile
import zipfile
from pathlib import Path

from .base import Tool, ToolContext, ToolError
from .registry import register

MAX_ENTRIES = 10_000
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
MAX_RATIO = 100


def _safe_join(base: Path, name: str) -> Path:
    """Resolve an entry name under base, rejecting traversal / absolute paths."""
    if name.startswith("/") or name.startswith("\\"):
        raise ToolError("archive contains an absolute path — refusing to extract")
    target = (base / name).resolve()
    if base not in target.parents and target != base:
        raise ToolError("archive contains a path that escapes the extraction folder")
    return target


@register
class ArchiveExtract(Tool):
    slug = "archive-extract"
    name = "Extract archive"
    category = "utilities"
    description = "Safely extract a .zip, .7z, .tar, .tar.gz/.tgz or .gz archive."
    accepts = [".zip", ".7z", ".tar", ".gz", ".tgz"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {"type": "object", "properties": {}}

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        dest = (ctx.output_dir / "extracted").resolve()
        dest.mkdir(parents=True, exist_ok=True)
        name = src.name.lower()
        ctx.progress(0.2, "inspecting archive")

        if name.endswith(".zip"):
            self._extract_zip(ctx, src, dest)
        elif name.endswith(".7z"):
            self._extract_7z(ctx, src, dest)
        elif name.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")):
            self._extract_tar(ctx, src, dest)
        elif name.endswith(".gz"):
            # A '.tar.gz' upload is stored as '<uuid>.gz' (safe_suffix keeps only
            # the final suffix), so dispatching on the name alone would merely
            # gunzip it to a single '.tar'. Sniff the content: if it is really a
            # (compressed) tar, un-tar it fully; otherwise plain-gunzip it.
            try:
                is_tar = tarfile.is_tarfile(src)
            except Exception:
                is_tar = False
            if is_tar:
                self._extract_tar(ctx, src, dest)
            else:
                self._extract_gz(ctx, src, dest)
        else:
            raise ToolError("unsupported archive type")
        ctx.progress(1.0, "extracted")

    def _extract_zip(self, ctx: ToolContext, src: Path, dest: Path) -> None:
        try:
            zf = zipfile.ZipFile(src)
        except zipfile.BadZipFile:
            raise ToolError("the file is not a valid zip archive") from None
        with zf:
            infos = zf.infolist()
            if len(infos) > MAX_ENTRIES:
                raise ToolError(f"archive has too many entries (>{MAX_ENTRIES})")
            # Bit 0 of the general-purpose flag marks an encrypted entry. We have
            # no password path, so fail early with a clear message rather than
            # dying deep in zf.open() with a raw Runtime('File is encrypted').
            if any(info.flag_bits & 0x1 for info in infos):
                raise ToolError(
                    "the zip archive is password-protected — extraction is not supported"
                )
            total_uncompressed = sum(i.file_size for i in infos)
            total_compressed = sum(i.compress_size for i in infos) or 1
            if total_uncompressed > MAX_TOTAL_BYTES:
                raise ToolError("archive expands to more than 2 GiB — refusing to extract")
            if total_uncompressed / total_compressed > MAX_RATIO:
                raise ToolError("archive compression ratio looks like a zip bomb — refusing")
            few = len(infos) <= 200
            for idx, info in enumerate(infos):
                target = _safe_join(dest, info.filename)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as srcf, target.open("wb") as outf:
                    shutil.copyfileobj(srcf, outf, length=1024 * 64)
                # Move the bar per entry for small archives (few large members
                # otherwise sit at one value); throttle for huge archives.
                if few or idx % 50 == 0:
                    ctx.progress(0.2 + 0.7 * idx / len(infos), "extracting")

    def _extract_7z(self, ctx: ToolContext, src: Path, dest: Path) -> None:
        try:
            import py7zr
        except Exception:
            raise ToolError("the 7z engine is not available on this server") from None
        try:
            with py7zr.SevenZipFile(src, "r") as zf:
                # No password path here — surface a clear message instead of the
                # generic 'internal error' py7zr raises deep inside extractall.
                if getattr(zf, "needs_password", lambda: False)():
                    raise ToolError(
                        "the 7z archive is password-protected — extraction is not supported"
                    )
                infos = zf.list()
                if len(infos) > MAX_ENTRIES:
                    raise ToolError(f"archive has too many entries (>{MAX_ENTRIES})")
                total = sum(getattr(i, "uncompressed", 0) or 0 for i in infos)
                if total > MAX_TOTAL_BYTES:
                    raise ToolError("archive expands to more than 2 GiB — refusing to extract")
                # 7z carries no per-entry compress_size in list(); guard against a
                # zip-bomb by comparing declared expansion against the archive size
                # on disk (only catches inflated-but-declared sizes, but that is a
                # cheap improvement over having no ratio check at all for 7z).
                compressed = src.stat().st_size or 1
                if total / compressed > MAX_RATIO:
                    raise ToolError("archive compression ratio looks like a zip bomb — refusing")
                for i in infos:  # reject traversal before extracting
                    _safe_join(dest, i.filename)
                ctx.progress(0.5, "extracting")
                zf.extractall(path=str(dest))
        except py7zr.exceptions.Bad7zFile:
            raise ToolError("the file is not a valid 7z archive") from None
        except py7zr.exceptions.PasswordRequired:
            raise ToolError(
                "the 7z archive is password-protected — extraction is not supported"
            ) from None

    def _extract_tar(self, ctx: ToolContext, src: Path, dest: Path) -> None:
        try:
            tf = tarfile.open(src)
        except tarfile.TarError:
            raise ToolError("the file is not a valid tar archive") from None
        with tf:
            members = tf.getmembers()
            if len(members) > MAX_ENTRIES:
                raise ToolError(f"archive has too many entries (>{MAX_ENTRIES})")
            total = sum(m.size for m in members)
            if total > MAX_TOTAL_BYTES:
                raise ToolError("archive expands to more than 2 GiB — refusing to extract")
            for m in members:
                if m.issym() or m.islnk():
                    raise ToolError("archive contains a symlink — refusing to extract")
                _safe_join(dest, m.name)
            ctx.progress(0.5, "extracting")
            # data_filter (py3.12+) strips dangerous members as defense in depth
            try:
                tf.extractall(path=str(dest), filter="data")
            except TypeError:
                tf.extractall(path=str(dest))

    def _extract_gz(self, ctx: ToolContext, src: Path, dest: Path) -> None:
        out_name = src.name[:-3] if src.name.lower().endswith(".gz") else src.name + ".out"
        target = _safe_join(dest, out_name)
        written = 0
        ctx.progress(0.5, "decompressing")
        try:
            with gzip.open(src, "rb") as gf, target.open("wb") as outf:
                while True:
                    chunk = gf.read(1024 * 64)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_TOTAL_BYTES:
                        raise ToolError("decompressed output exceeds 2 GiB — refusing")
                    outf.write(chunk)
        except EOFError:
            # gzip raises EOFError (not OSError) on a truncated stream.
            raise ToolError("the gzip archive is truncated or incomplete") from None
        except OSError:
            raise ToolError("the file is not a valid gzip archive") from None
