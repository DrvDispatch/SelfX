"""Tool base class, ToolContext and run_cmd helper (SPEC §6)."""

import logging
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path

from ..config import settings

logger = logging.getLogger("selfx.tools")


class ToolError(Exception):
    """Raised by tools with a USER-SAFE message (no raw paths, no tracebacks)."""


class ToolContext:
    """Everything a tool needs for one job run."""

    def __init__(
        self,
        job_id: uuid.UUID,
        input_paths: list[Path],
        params: dict,
        workdir: Path,
        output_dir: Path,
        progress_cb: Callable[[float, str], None] | None = None,
    ) -> None:
        self.job_id = job_id
        self.input_paths = input_paths
        self.params = params
        self.workdir = workdir
        self.output_dir = output_dir
        self._progress_cb = progress_cb

    def progress(self, fraction: float, message: str = "") -> None:
        """Report progress (0..1) and an optional current-step message to the jobs row."""
        fraction = max(0.0, min(1.0, float(fraction)))
        if self._progress_cb is None:
            return
        try:
            self._progress_cb(fraction, message)
        except Exception:
            logger.warning("progress update failed for job %s", self.job_id, exc_info=True)

    def run_cmd(
        self, args: list[str], timeout: int | None = None, **kw
    ) -> subprocess.CompletedProcess:
        """Run a subprocess: ALWAYS list args, shell=False, cwd=workdir, captured output.

        Raises ToolError with the stderr tail on nonzero exit. User-controlled values
        must only ever be passed as file paths or validated enum/number params.
        """
        argv = [str(a) for a in args]
        if not argv:
            raise ToolError("empty command")
        prog = Path(argv[0]).name
        if timeout is None:
            timeout = settings.job_timeout_seconds
        kw.setdefault("cwd", str(self.workdir))
        if "stdout" not in kw and "stderr" not in kw and not kw.get("capture_output"):
            kw["capture_output"] = True
        kw.setdefault("text", True)
        try:
            proc = subprocess.run(argv, shell=False, timeout=timeout, check=False, **kw)
        except FileNotFoundError:
            raise ToolError(f"required program '{prog}' is not installed") from None
        except subprocess.TimeoutExpired:
            raise ToolError(f"'{prog}' timed out after {timeout} seconds") from None
        if proc.returncode != 0:
            stderr = proc.stderr
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            tail = (stderr or "").strip()[-500:]
            raise ToolError(f"'{prog}' failed (exit {proc.returncode}): {tail or 'no error output'}")
        return proc


class Tool:
    """Base class for all tool adapters. Subclass, set the class attrs, add @register."""

    slug: str = ""
    name: str = ""
    category: str = ""
    description: str = ""
    accepts: list[str] = []  # allowed input extensions, [] = no file input
    multi_file: bool = False
    min_files: int = 1  # 0 for param-only tools (e.g. QR)
    params_schema: dict = {"type": "object", "properties": {}}
    queue: str = "default"  # "heavy" for media/AI

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def run(self, ctx: ToolContext) -> None:
        raise NotImplementedError
