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
from ._media import guard_output_size, probe
from .base import Tool, ToolContext, ToolError
from .registry import register

# preset -> (output extension, argv fragment appended after the input).
# webm-vp9 is tuned for the CPU-only box: -cpu-used 4 -deadline good keeps libvpx
# out of its brutally-slow default, and -row-mt/-tile-columns use multiple cores.
_PRESETS: dict[str, tuple[str, list[str]]] = {
    "mp4-h264": ("mp4", ["-c:v", "libx264", "-preset", "medium", "-c:a", "aac",
                          "-b:a", "160k", "-movflags", "+faststart"]),
    "webm-vp9": ("webm", ["-c:v", "libvpx-vp9", "-b:v", "0",
                          "-cpu-used", "4", "-deadline", "good",
                          "-row-mt", "1", "-tile-columns", "2",
                          "-c:a", "libopus"]),
    "mp3": ("mp3", ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]),
    "opus": ("opus", ["-vn", "-c:a", "libopus", "-b:a", "128k"]),
    "wav": ("wav", ["-vn", "-c:a", "pcm_s16le"]),
    "flac": ("flac", ["-vn", "-c:a", "flac"]),
    "gif": ("gif", ["-vf",
                    "fps=12,scale=480:-1:flags=lanczos,split[s0][s1];"
                    "[s0]palettegen[p];[s1][p]paletteuse"]),
}

# libx264 -preset choices, exposed so a CPU-bound user can trade speed for size.
_X264_SPEEDS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
                "medium", "slow", "slower", "veryslow"]

# Hard duration cap (seconds) for the gif preset — it has no duration param, so a
# 2-hour source would otherwise feed the whole timeline through palettegen.
_GIF_MAX_SECONDS = 30


def _copy_override(info: dict, preset: str) -> list[str] | None:
    """Return a stream-copy fragment when the source already matches the target.

    Turns a container change / same-codec convert into a near-instant, lossless
    remux instead of a full re-encode. Returns None when a re-encode is required.
    """
    ac, vc = info.get("acodec"), info.get("vcodec")
    has_a, has_v = info.get("audio"), info.get("video")
    if preset == "mp4-h264":
        if has_v and vc == "h264" and (not has_a or ac == "aac"):
            return ["-c:v", "copy", "-c:a", "copy", "-movflags", "+faststart"]
    elif preset == "webm-vp9":
        if has_v and vc in ("vp9",) and (not has_a or ac in ("opus", "vorbis")):
            return ["-c:v", "copy", "-c:a", "copy"]
    elif preset == "mp3" and ac == "mp3":
        return ["-vn", "-c:a", "copy"]
    elif preset == "opus" and ac == "opus":
        return ["-vn", "-c:a", "copy"]
    elif preset == "flac" and ac == "flac":
        return ["-vn", "-c:a", "copy"]
    elif preset == "wav" and ac == "pcm_s16le":
        return ["-vn", "-c:a", "copy"]
    return None


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
            "speed": {
                "type": "string",
                "title": "Encoder speed (mp4/h264)",
                "description": "Faster = quicker encode, larger file. Only used for mp4-h264.",
                "enum": _X264_SPEEDS,
                "default": "medium",
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

        info = probe(ctx, src)
        # Friendly, distinct errors instead of an opaque ffmpeg "no stream" tail.
        # Only reject when the probe clearly worked, so a probe failure can't
        # falsely block a real conversion.
        probe_worked = info["video"] or info["audio"] or info["duration"] is not None
        if probe_worked:
            if preset in ("mp4-h264", "webm-vp9", "gif") and not info["video"]:
                raise ToolError(
                    "this file has no video track — pick an audio format "
                    "(mp3, opus, wav, flac) instead"
                )
            if preset in ("mp3", "opus", "wav", "flac") and not info["audio"]:
                raise ToolError("this file has no audio track to convert")
        duration = info["duration"] or self._duration(ctx, src)

        argv = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src)]
        override = None if preset == "gif" else _copy_override(info, preset)
        if override is not None:
            # Same-codec / container-only change: lossless remux, no re-encode.
            argv += override
            ctx.progress(0.05, "remuxing (no re-encode)")
        else:
            frag = list(frag)
            if preset == "mp4-h264":
                speed = str(ctx.params.get("speed", "medium"))
                if speed in _X264_SPEEDS and "-preset" in frag:
                    frag[frag.index("-preset") + 1] = speed
            argv += frag
            crf = ctx.params.get("crf")
            if crf is None and preset == "webm-vp9":
                crf = 32  # VP9 CQ mode needs a -crf; -b:v 0 alone is undefined quality
            if crf is not None and preset in ("mp4-h264", "webm-vp9"):
                argv += ["-crf", str(int(crf))]
            if preset == "gif":
                argv += ["-t", str(_GIF_MAX_SECONDS)]
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
                # Give the finalize/mux as long as the remaining job budget allows
                # (a large mp4/webm on slow disk can legitimately take >30s).
                ret = proc.wait(timeout=max(30.0, deadline - time.monotonic()))
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
        guard_output_size(out_path, "converted file")
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
