"""File storage: streamed upload saving, path helpers, mime sniffing, ClamAV scan (SPEC §4, §10)."""

import logging
import os
import re
import socket
import uuid
from pathlib import Path
from typing import BinaryIO

import magic

from .config import settings

logger = logging.getLogger("selfx.storage")

CHUNK_SIZE = 1024 * 1024
SNIFF_BYTES = 8192
FALLBACK_MIME = "application/octet-stream"


class UploadTooLarge(Exception):
    pass


class EmptyUpload(Exception):
    pass


class VirusFound(Exception):
    def __init__(self, signature: str):
        super().__init__(signature)
        self.signature = signature


def data_dir() -> Path:
    return Path(settings.data_dir)


def uploads_dir() -> Path:
    return data_dir() / "uploads"


def outputs_dir(job_id: uuid.UUID | str) -> Path:
    return data_dir() / "outputs" / str(job_id)


def tmp_dir(job_id: uuid.UUID | str) -> Path:
    return data_dir() / "tmp" / str(job_id)


def file_abs_path(stored_path: str) -> Path:
    return data_dir() / stored_path


def ensure_dirs() -> None:
    for p in (uploads_dir(), data_dir() / "outputs", data_dir() / "tmp"):
        p.mkdir(parents=True, exist_ok=True)


def sanitize_orig_name(name: str) -> str:
    """Strip path separators and control chars, cap at 255 chars (SPEC §4)."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ord(ch) >= 32 and ch != "\x7f").strip()
    if name in ("", ".", ".."):
        name = "file"
    return name[:255]


def safe_suffix(name: str) -> str:
    suffix = Path(sanitize_orig_name(name)).suffix.lower()
    return re.sub(r"[^a-z0-9.]", "", suffix)[:16]


def sniff_mime_buffer(buf: bytes) -> str:
    try:
        return magic.from_buffer(buf, mime=True) or FALLBACK_MIME
    except Exception:
        return FALLBACK_MIME


def sniff_mime_file(path: Path) -> str:
    try:
        return magic.from_file(str(path), mime=True) or FALLBACK_MIME
    except Exception:
        return FALLBACK_MIME


def save_upload(stream: BinaryIO, orig_name: str) -> tuple[uuid.UUID, str, int, str]:
    """Stream an upload to /data/uploads/<uuid><suffix>, enforcing MAX_UPLOAD_MB.

    Returns (file_id, stored_path relative to DATA_DIR, size, sniffed mime).
    Never buffers the whole file in RAM (SPEC §10).
    """
    ensure_dirs()
    file_id = uuid.uuid4()
    stored_rel = f"uploads/{file_id}{safe_suffix(orig_name)}"
    dest = data_dir() / stored_rel
    size = 0
    head = b""
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise UploadTooLarge()
                if len(head) < SNIFF_BYTES:
                    head += chunk[: SNIFF_BYTES - len(head)]
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    if size == 0:
        dest.unlink(missing_ok=True)
        raise EmptyUpload()
    return file_id, stored_rel, size, sniff_mime_buffer(head)


def delete_stored_file(stored_path: str) -> None:
    try:
        file_abs_path(stored_path).unlink(missing_ok=True)
    except OSError:
        logger.warning("could not delete stored file %s", stored_path)


def disk_used_bytes() -> int:
    total = 0
    for root, _dirs, names in os.walk(data_dir()):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def clamav_scan(path: Path) -> None:
    """Scan a file via clamd INSTREAM. Raises VirusFound or RuntimeError on scanner failure."""
    with socket.create_connection((settings.clamav_host, settings.clamav_port), timeout=120) as sock:
        sock.sendall(b"zINSTREAM\x00")
        with open(path, "rb") as fh:
            while chunk := fh.read(65536):
                sock.sendall(len(chunk).to_bytes(4, "big"))
                sock.sendall(chunk)
        sock.sendall((0).to_bytes(4, "big"))
        parts: list[bytes] = []
        while True:
            data = sock.recv(4096)
            if not data:
                break
            parts.append(data)
    reply = b"".join(parts).decode("utf-8", "replace").strip("\x00").strip()
    if reply.endswith("OK"):
        return
    if reply.endswith("FOUND"):
        signature = reply.split(":", 1)[-1].rsplit("FOUND", 1)[0].strip()
        raise VirusFound(signature or "unknown signature")
    raise RuntimeError(f"unexpected clamd reply: {reply[:200]}")
