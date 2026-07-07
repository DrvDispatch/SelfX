"""virus-scan: scan a file for malware with the ClamAV daemon (clamd INSTREAM)."""

import socket
import struct

from ..config import settings
from .base import Tool, ToolContext, ToolError
from .registry import register


def _scan_stream(path, host: str, port: int) -> str:
    """Send the file to clamd via INSTREAM and return its raw reply."""
    with socket.create_connection((host, port), timeout=60) as s:
        s.sendall(b"zINSTREAM\0")
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                s.sendall(struct.pack("!L", len(chunk)) + chunk)
        s.sendall(struct.pack("!L", 0))  # zero-length chunk = end of stream
        reply = b""
        while True:
            data = s.recv(4096)
            if not data:
                break
            reply += data
    return reply.decode("utf-8", "replace").strip().rstrip("\0")


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
    params_schema = {"type": "object", "properties": {}}

    def available(self) -> tuple[bool, str | None]:
        try:
            with socket.create_connection((settings.clamav_host, settings.clamav_port), timeout=2):
                return True, None
        except Exception:
            return False, "the virus scanner (ClamAV daemon) is not running"

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        ctx.progress(0.3, "scanning for malware")
        try:
            reply = _scan_stream(src, settings.clamav_host, settings.clamav_port)
        except socket.timeout:
            raise ToolError("the virus scan timed out") from None
        except BrokenPipeError:
            # clamd closes the connection mid-send when a file exceeds its
            # StreamMaxLength — the daemon is fine, the file is just too big.
            raise ToolError(
                "the file exceeds the virus scanner's stream size limit"
            ) from None
        except OSError:
            raise ToolError("could not reach the virus scanner") from None

        # clamd replies e.g. "stream: OK" or "stream: Eicar-Test-Signature FOUND"
        if reply.endswith("OK"):
            verdict = "CLEAN — no threats found"
        elif "FOUND" in reply:
            sig = reply.split(":", 1)[-1].replace("FOUND", "").strip()
            verdict = f"INFECTED — {sig}"
        elif "size limit" in reply.lower():
            raise ToolError("the file exceeds the virus scanner's stream size limit")
        elif "ERROR" in reply.upper():
            # A clamd error reply (e.g. "INSTREAM size limit exceeded. ERROR") is a
            # scan FAILURE, not a result — don't record it as a successful verdict.
            raise ToolError(f"the virus scanner reported an error: {reply}")
        else:
            verdict = reply or "unknown scan result"
        (ctx.output_dir / "scan-result.txt").write_text(
            f"file: {src.name}\nresult: {verdict}\n", encoding="utf-8"
        )
        ctx.progress(1.0, verdict)
