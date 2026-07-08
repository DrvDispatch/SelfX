"""virus-scan: scan a file for malware with the ClamAV daemon (clamd INSTREAM/SCAN)."""

import socket
import struct

from ..config import settings
from .base import Tool, ToolContext, ToolError
from .registry import register

_CHUNK = 262144  # 256 KiB — fewer syscalls/length-prefixes than the old 64 KiB


def _scan_stream(path, host: str, port: int, on_progress=None) -> str:
    """Send the file to clamd via INSTREAM and return its raw reply."""
    try:
        total = path.stat().st_size or 0
    except OSError:
        total = 0
    sent = 0
    with socket.create_connection((host, port), timeout=60) as s:
        s.sendall(b"zINSTREAM\0")
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(_CHUNK)
                if not chunk:
                    break
                s.sendall(struct.pack("!L", len(chunk)) + chunk)
                sent += len(chunk)
                if on_progress and total:
                    on_progress(sent / total)
        s.sendall(struct.pack("!L", 0))  # zero-length chunk = end of stream
        reply = b""
        while True:
            data = s.recv(4096)
            if not data:
                break
            reply += data
    return reply.decode("utf-8", "replace").strip().rstrip("\0")


def _scan_path(path, host: str, port: int) -> str:
    """Ask clamd to SCAN a filesystem path directly (no stream-size limit)."""
    with socket.create_connection((host, port), timeout=60) as s:
        s.sendall(b"zSCAN " + str(path).encode("utf-8") + b"\0")
        reply = b""
        while True:
            data = s.recv(4096)
            if not data:
                break
            reply += data
    return reply.decode("utf-8", "replace").strip().rstrip("\0")


def _get_version(host: str, port: int) -> str:
    """Query the clamd engine + signature DB version (best effort)."""
    try:
        with socket.create_connection((host, port), timeout=5) as s:
            s.sendall(b"zVERSION\0")
            reply = b""
            while True:
                data = s.recv(4096)
                if not data:
                    break
                reply += data
        return reply.decode("utf-8", "replace").strip().rstrip("\0")
    except Exception:
        return ""


@register
class VirusScan(Tool):
    slug = "virus-scan"
    name = "Virus scan"
    category = "utilities"
    description = "Scan a file for malware/viruses with ClamAV and report whether it is clean."
    accepts = []  # any file
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "scan_mode": {
                "type": "string",
                "title": "Scan mode",
                "description": (
                    "stream = upload the file to the scanner (default; works with a "
                    "remote daemon). path = have the daemon read the file directly — "
                    "no size limit, but only works when it shares this filesystem."
                ),
                "enum": ["stream", "path"],
                "default": "stream",
            },
            "report_version": {
                "type": "boolean",
                "title": "Record engine version",
                "description": "Include the ClamAV engine + signature DB version in the result.",
                "default": False,
            },
        },
    }

    def available(self) -> tuple[bool, str | None]:
        try:
            with socket.create_connection((settings.clamav_host, settings.clamav_port), timeout=2):
                return True, None
        except Exception:
            return False, "the virus scanner (ClamAV daemon) is not running"

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        mode = str(ctx.params.get("scan_mode", "stream"))
        host, port = settings.clamav_host, settings.clamav_port
        ctx.progress(0.3, "scanning for malware")
        try:
            if mode == "path":
                reply = _scan_path(src.resolve(), host, port)
            else:
                reply = _scan_stream(
                    src, host, port,
                    on_progress=lambda f: ctx.progress(0.3 + 0.6 * f, "scanning for malware"),
                )
        except socket.timeout:
            raise ToolError("the virus scan timed out") from None
        except BrokenPipeError:
            # clamd closes the connection mid-send when a file exceeds its
            # StreamMaxLength — the daemon is fine, the file is just too big.
            raise ToolError(
                "the file exceeds the virus scanner's stream size limit "
                "(try the 'path' scan mode for large local files)"
            ) from None
        except OSError:
            raise ToolError("could not reach the virus scanner") from None

        # clamd replies e.g. "stream: OK" or "stream: Eicar-Test-Signature FOUND".
        # Use rsplit so a Windows path (with a drive-letter colon) in SCAN mode
        # doesn't confuse the signature extraction.
        if reply.endswith("OK"):
            verdict = "CLEAN — no threats found"
        elif "FOUND" in reply:
            sig = reply.rsplit(":", 1)[-1].replace("FOUND", "").strip()
            verdict = f"INFECTED — {sig}"
        elif "size limit" in reply.lower():
            raise ToolError("the file exceeds the virus scanner's stream size limit")
        elif "ERROR" in reply.upper():
            # A clamd error reply (e.g. "INSTREAM size limit exceeded. ERROR") is a
            # scan FAILURE, not a result — don't record it as a successful verdict.
            raise ToolError(f"the virus scanner reported an error: {reply}")
        else:
            verdict = reply or "unknown scan result"

        lines = [f"file: {src.name}", f"result: {verdict}"]
        if bool(ctx.params.get("report_version", False)):
            version = _get_version(host, port)
            if version:
                lines.append(f"engine: {version}")
        (ctx.output_dir / "scan-result.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        ctx.progress(1.0, verdict)
