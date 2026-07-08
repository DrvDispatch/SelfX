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
    # GPU hardware encoders (NVIDIA NVENC) — many times faster than libx264/libx265
    # when the video actually needs re-encoding. Falls back to a clear ffmpeg error
    # on a box without an NVIDIA GPU. Video args are built in _video_plan.
    "mp4-nvenc-h264": ("mp4", []),
    "mp4-nvenc-hevc": ("mp4", []),
}

# preset -> (nvenc encoder, target vcodec for the copy-if-already-matching check)
_NVENC: dict[str, tuple[str, str]] = {
    "mp4-nvenc-h264": ("h264_nvenc", "h264"),
    "mp4-nvenc-hevc": ("hevc_nvenc", "hevc"),
}

# The presets that re-encode video; they support per-stream copy decisions.
_VIDEO_PRESETS = ("mp4-h264", "webm-vp9", "mp4-nvenc-h264", "mp4-nvenc-hevc")

# The libvpx-vp9 video-only encoder args, shared by the single-pass fragment and
# the optional two-pass analysis run.
_VP9_VIDEO_ARGS = ["-c:v", "libvpx-vp9", "-b:v", "0", "-cpu-used", "4",
                   "-deadline", "good", "-row-mt", "1", "-tile-columns", "2"]

# libx264 -preset choices, exposed so a CPU-bound user can trade speed for size.
_X264_SPEEDS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
                "medium", "slow", "slower", "veryslow"]

# Hard duration cap (seconds) for the gif preset — it has no duration param, so a
# 2-hour source would otherwise feed the whole timeline through palettegen.
_GIF_MAX_SECONDS = 30

_POSIX = os.name == "posix"


def _copy_override(info: dict, preset: str) -> list[str] | None:
    """Return a stream-copy fragment when an AUDIO source already matches the target.

    Turns a same-codec convert into a near-instant, lossless remux instead of a
    full re-encode. Returns None when a re-encode is required. (Video presets use
    the richer per-stream `_video_plan` instead.)
    """
    ac = info.get("acodec")
    if preset == "mp3" and ac == "mp3":
        return ["-vn", "-c:a", "copy"]
    elif preset == "opus" and ac == "opus":
        return ["-vn", "-c:a", "copy"]
    elif preset == "flac" and ac == "flac":
        return ["-vn", "-c:a", "copy"]
    elif preset == "wav" and ac == "pcm_s16le":
        return ["-vn", "-c:a", "copy"]
    return None


def _video_plan(info: dict, preset: str, speed: str) -> tuple[list[str], bool, str]:
    """Per-stream copy/encode plan for the two video presets.

    Copies any stream already compatible with the target container (lossless and
    near-instant) and re-encodes ONLY the mismatched stream(s). Returns
    (fragment, video_is_re_encoded, progress_note). This is strictly better than
    a blanket re-encode: an already-h264 track destined for mp4 (or vp9 for webm)
    is stream-copied even when the audio has to be transcoded, and vice-versa.
    """
    vc, ac = info.get("vcodec"), info.get("acodec")
    has_v, has_a = info.get("video"), info.get("audio")
    frag: list[str] = []
    venc = False
    a_copied = False

    if preset in _NVENC:
        enc, target = _NVENC[preset]
        if has_v and vc == target:
            frag += ["-c:v", "copy"]
        else:
            # p5 = balanced NVENC preset; VBR rate control with a -cq target added in run()
            frag += ["-c:v", enc, "-preset", "p5", "-rc", "vbr"]
            venc = True
        if has_a:
            if ac == "aac":
                frag += ["-c:a", "copy"]
                a_copied = True
            else:
                frag += ["-c:a", "aac", "-b:a", "160k"]
        frag += ["-movflags", "+faststart"]
    elif preset == "mp4-h264":
        if has_v and vc == "h264":
            frag += ["-c:v", "copy"]
        else:
            frag += ["-c:v", "libx264", "-preset", speed]
            venc = True
        if has_a:
            if ac == "aac":
                frag += ["-c:a", "copy"]
                a_copied = True
            else:
                frag += ["-c:a", "aac", "-b:a", "160k"]
        frag += ["-movflags", "+faststart"]
    else:  # webm-vp9
        if has_v and vc == "vp9":
            frag += ["-c:v", "copy"]
        else:
            frag += list(_VP9_VIDEO_ARGS)
            venc = True
        if has_a:
            if ac in ("opus", "vorbis"):
                frag += ["-c:a", "copy"]
                a_copied = True
            else:
                frag += ["-c:a", "libopus"]

    if not venc and (a_copied or not has_a):
        note = "remuxing (no re-encode)"
    elif not venc or a_copied:
        note = "converting (partial copy)"
    else:
        note = "converting"
    return frag, venc, note


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
                "title": "Quality (CRF / CQ)",
                "description": "Lower = better/larger. Used for mp4/webm re-encodes; "
                               "for the GPU NVENC presets this sets the CQ target (0-51).",
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
            "two_pass": {
                "type": "boolean",
                "title": "Two-pass (webm-vp9)",
                "description": "Analyse then encode for better quality-per-bit. "
                               "Only used for webm-vp9 re-encodes; roughly doubles encode time.",
                "default": False,
            },
            "subtitles": {
                "type": "string",
                "title": "Subtitles",
                "description": "Keep source subtitle handling, or drop subtitles "
                               "(avoids remux failures on incompatible subtitle streams).",
                "enum": ["auto", "none"],
                "default": "auto",
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

        if preset in _VIDEO_PRESETS:
            speed = str(ctx.params.get("speed", "medium"))
            if speed not in _X264_SPEEDS:
                speed = "medium"
            plan, venc, note = _video_plan(info, preset, speed)
            argv += plan
            crf = ctx.params.get("crf")
            if venc:
                if crf is None and preset == "webm-vp9":
                    crf = 32  # VP9 CQ mode needs a -crf; -b:v 0 alone is undefined quality
                if crf is None and preset in _NVENC:
                    crf = 23 if preset == "mp4-nvenc-h264" else 26  # NVENC needs a -cq target
                if crf is not None:
                    # NVENC uses -cq (constant quality) rather than libx264/libvpx -crf
                    argv += (["-cq", str(int(crf))] if preset in _NVENC else ["-crf", str(int(crf))])
                if str(ctx.params.get("subtitles", "auto")) == "none":
                    argv += ["-sn"]
                # Optional two-pass VP9: run the analysis pass now, then tell the
                # main (progress-tracked) encode to consume the stats.
                if preset == "webm-vp9" and bool(ctx.params.get("two_pass", False)):
                    passlog = ctx.workdir / "ffmpeg2pass"
                    crf_val = crf if crf is not None else 32
                    pass1 = (["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src)]
                             + list(_VP9_VIDEO_ARGS)
                             + ["-crf", str(int(crf_val)), "-pass", "1",
                                "-passlogfile", str(passlog), "-an", "-f", "null",
                                os.devnull])
                    ctx.progress(0.05, "analysing (pass 1 of 2)")
                    ctx.run_cmd(pass1)
                    argv += ["-pass", "2", "-passlogfile", str(passlog)]
            else:
                # Pure/partial copy: a stream-copy container change can still trip
                # over an incompatible subtitle stream — honour the drop request.
                if str(ctx.params.get("subtitles", "auto")) == "none":
                    argv += ["-sn"]
            ctx.progress(0.05, note)
        elif preset == "gif":
            argv += list(frag)
            argv += ["-t", str(_GIF_MAX_SECONDS)]
        else:
            # Audio presets: same-codec source -> lossless remux, else re-encode.
            override = _copy_override(info, preset)
            if override is not None:
                argv += override
                ctx.progress(0.05, "remuxing (no re-encode)")
            else:
                argv += list(frag)

        argv += ["-progress", "pipe:1", "-nostats", str(out_path)]

        err_path = ctx.workdir / "ffmpeg.err"
        ctx.progress(0.02, "starting conversion")
        deadline = time.monotonic() + settings.job_timeout_seconds
        popen_kw: dict = {}
        if _POSIX:
            popen_kw["start_new_session"] = True  # own process group -> clean kill
        elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        with err_path.open("wb") as err_fh:
            proc = subprocess.Popen(
                argv,
                cwd=str(ctx.workdir),
                stdout=subprocess.PIPE,
                stderr=err_fh,
                text=True,
                **popen_kw,
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
            if _POSIX:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                # Native Windows: killpg/getpgid don't exist — kill the whole tree.
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except Exception:
                pass
