"""media-convert: audio/video conversion with FFmpeg and live progress (SPEC §8).

FFmpeg is driven directly (argv list, never a shell string). Progress comes from
`-progress pipe:1`; stderr is redirected to a file to avoid pipe-buffer deadlock,
and the whole process group is killed on timeout so no orphan ffmpeg survives.
"""

import os
import signal
import subprocess
import time

from ..config import settings
from .base import Tool, ToolContext, ToolError
from .registry import register

# preset -> (output extension, argv fragment appended after the input)
_PRESETS: dict[str, tuple[str, list[str]]] = {
    "mp4-h264": ("mp4", ["-c:v", "libx264", "-preset", "medium", "-c:a", "aac",
                          "-b:a", "160k", "-movflags", "+faststart"]),
    "webm-vp9": ("webm", ["-c:v", "libvpx-vp9", "-b:v", "0", "-row-mt", "1",
                          "-c:a", "libopus"]),
    "mp3": ("mp3", ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]),
    "opus": ("opus", ["-vn", "-c:a", "libopus", "-b:a", "128k"]),
    "wav": ("wav", ["-vn", "-c:a", "pcm_s16le"]),
    "flac": ("flac", ["-vn", "-c:a", "flac"]),
    "gif": ("gif", ["-vf",
                    "fps=12,scale=480:-1:flags=lanczos,split[s0][s1];"
                    "[s0]palettegen[p];[s1][p]paletteuse"]),
}


@register
class MediaConvert(Tool):
    slug = "media-convert"
    name = "Audio / Video convert"
    category = "media"
    description = "Transcode audio or video with FFmpeg (mp4, webm, mp3, opus, wav, flac, gif)."
    accepts = [
        ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg", ".3gp",
        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".opus", ".m4a", ".wma", ".aiff",
    ]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "preset": {
                "type": "string",
                "title": "Convert to",
                "enum": list(_PRESETS.keys()),
                "default": "mp4-h264",
            },
            "crf": {
                "type": "integer",
                "title": "Quality (CRF)",
                "description": "Lower = better/larger. Only used for mp4/webm (0-51).",
                "minimum": 0,
                "maximum": 51,
            },
        },
        "required": ["preset"],
    }

    def _duration(self, ctx: ToolContext, src) -> float:
        try:
            proc = ctx.run_cmd(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(src)],
                timeout=60,
            )
            return float((proc.stdout or "").strip())
        except (ToolError, ValueError):
            return 0.0

    def run(self, ctx: ToolContext) -> None:
        preset = str(ctx.params.get("preset", "mp4-h264"))
        spec = _PRESETS.get(preset)
        if spec is None:
            raise ToolError(f"unknown preset '{preset}'")
        ext, frag = spec
        src = ctx.input_paths[0]
        out_path = ctx.output_dir / f"{src.stem}.{ext}"
        duration = self._duration(ctx, src)

        argv = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src)]
        argv += list(frag)
        crf = ctx.params.get("crf")
        if crf is not None and preset in ("mp4-h264", "webm-vp9"):
            argv += ["-crf", str(int(crf))]
        argv += ["-progress", "pipe:1", "-nostats", str(out_path)]

        err_path = ctx.workdir / "ffmpeg.err"
        ctx.progress(0.02, "starting conversion")
        deadline = time.monotonic() + settings.job_timeout_seconds
        with err_path.open("wb") as err_fh:
            proc = subprocess.Popen(
                argv,
                cwd=str(ctx.workdir),
                stdout=subprocess.PIPE,
                stderr=err_fh,
                text=True,
                start_new_session=True,  # own process group -> clean kill
            )
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    if time.monotonic() > deadline:
                        self._kill(proc)
                        raise ToolError(
                            f"conversion exceeded the time limit of {settings.job_timeout_seconds}s"
                        )
                    key, _, value = line.strip().partition("=")
                    if key == "out_time_us" and duration > 0:
                        try:
                            secs = int(value) / 1_000_000
                            ctx.progress(min(0.98, secs / duration), "converting")
                        except ValueError:
                            pass
                    elif key == "progress" and value == "end":
                        ctx.progress(0.99, "finalizing")
                ret = proc.wait(timeout=30)
            except ToolError:
                raise
            except Exception:
                self._kill(proc)
                raise ToolError("the conversion process failed unexpectedly") from None

        if ret != 0:
            tail = err_path.read_text("utf-8", "replace").strip()[-400:] if err_path.exists() else ""
            raise ToolError(f"ffmpeg failed: {tail or 'the input may be unsupported or corrupt'}")
        if not out_path.is_file() or out_path.stat().st_size == 0:
            raise ToolError("conversion produced no output")
        ctx.progress(1.0, "done")

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except Exception:
                pass
