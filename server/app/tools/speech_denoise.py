"""speech-denoise: remove steady background noise (fan, A/C, ventilator, hiss) from
audio OR video, keeping the video stream and choosing how aggressively to clean.

Uses spectral-gating noise reduction (noisereduce), which is strongest exactly on
constant broadband noise like fans/ventilators. For a video input the original video
is kept and only its audio is cleaned; for audio the original format is preserved.
"""

from ._media import audio_bitrate_arg, guard_output_size, probe
from .base import Tool, ToolContext, ToolError
from .registry import register

_VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".flv", ".wmv"}

# container -> a compatible audio encoder, so the cleaned track is remuxed back into
# the ORIGINAL container instead of being forced into mp4 (which breaks VP8/VP9).
_CONTAINER_ACODEC = {".mp4": "aac", ".m4v": "aac", ".mov": "aac", ".mkv": "aac",
                     ".webm": "libopus", ".avi": "libmp3lame", ".flv": "aac",
                     ".wmv": "wmav2"}
_FASTSTART_EXT = {".mp4", ".m4v", ".mov"}

# how much detected noise to remove (noisereduce prop_decrease). Lower keeps more of
# the natural ambience; higher scrubs harder (can sound processed at "max").
_STRENGTH = {"light": 0.5, "medium": 0.75, "strong": 0.9, "max": 1.0}


@register
class SpeechDenoise(Tool):
    slug = "speech-denoise"
    name = "Remove background noise"
    category = "media"
    description = ("Remove steady background noise — fan, ventilator, A/C, hum, hiss — from an "
                   "audio or video file. For video the picture is kept and only the audio is cleaned.")
    accepts = [".mp3", ".wav", ".flac", ".aac", ".ogg", ".opus", ".m4a", ".wma", ".aiff",
               ".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".flv", ".wmv"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "strength": {
                "type": "string",
                "title": "Noise removal strength",
                "description": "light keeps more ambience; strong/max scrub heavy fan/ventilator noise",
                "enum": ["light", "medium", "strong", "max"],
                "default": "strong",
            },
            "noise_type": {
                "type": "string",
                "title": "Noise type",
                "description": ("steady = constant fan/hum/hiss (default); varying = noise that "
                                "changes over time (adaptive, tracks a shifting noise floor)"),
                "enum": ["steady", "varying"],
                "default": "steady",
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        import noisereduce as nr
        import numpy as np
        from scipy.io import wavfile

        strength = str(ctx.params.get("strength", "strong"))
        prop = _STRENGTH.get(strength, 0.9)
        # steady -> stationary spectral gating (current default); varying -> adaptive
        # mode that tracks a changing noise floor (typing, passing traffic, babble).
        noise_type = str(ctx.params.get("noise_type", "steady")).strip().lower()
        stationary = noise_type != "varying"
        src = ctx.input_paths[0]

        info = probe(ctx, src)
        probe_worked = info["video"] or info["audio"] or info["duration"] is not None
        if probe_worked and not info["audio"]:
            raise ToolError("this file has no audio track to denoise")
        # only treat as video when a real video stream is actually present, so an
        # audio-only .mov/.mp4 falls back to the audio path instead of failing -map.
        is_video = src.suffix.lower() in _VIDEO_EXT and info["video"]

        # 1) decode the audio track to WAV (preserving sample rate + channels)
        wav_in = ctx.workdir / "audio.wav"
        ctx.progress(0.15, "decoding audio")
        ctx.run_cmd(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
                     "-vn", "-c:a", "pcm_s16le", str(wav_in)])

        # 2) normalise to float, reduce noise per channel. Guard empty/too-short
        # inputs and wrap the numpy/noisereduce work in a user-safe error.
        wav_out = ctx.workdir / "clean.wav"
        ctx.progress(0.45, f"removing background noise ({strength})")
        try:
            sr, data = wavfile.read(str(wav_in))
            if data.size == 0 or data.shape[0] < 2048:
                raise ToolError("the audio is empty or too short to denoise")
            if data.dtype == np.int16:
                y = data.astype(np.float32) / 32768.0
            elif data.dtype == np.int32:
                y = data.astype(np.float32) / 2147483648.0
            elif data.dtype == np.uint8:
                y = (data.astype(np.float32) - 128.0) / 128.0
            else:
                y = data.astype(np.float32)

            if y.ndim == 1:
                cleaned = nr.reduce_noise(y=y, sr=sr, stationary=stationary, prop_decrease=prop)
            else:  # (samples, channels) -> clean each channel
                chans = [nr.reduce_noise(y=y[:, c], sr=sr, stationary=stationary, prop_decrease=prop)
                         for c in range(y.shape[1])]
                cleaned = np.stack(chans, axis=1)
            wavfile.write(str(wav_out), sr,
                          (np.clip(cleaned, -1.0, 1.0) * 32767).astype(np.int16))
        except ToolError:
            raise
        except Exception:
            raise ToolError(
                "could not process this audio — it may be empty, too short, or in an "
                "unusual format"
            ) from None

        # 3) rebuild the output: remux cleaned audio into the original container,
        # or re-encode audio (carrying the source bitrate).
        ctx.progress(0.8, "writing output")
        if is_video:
            suffix = src.suffix.lower()
            acodec = _CONTAINER_ACODEC.get(suffix, "aac")
            out = ctx.output_dir / f"{src.stem}-denoised{suffix}"
            argv = ["ffmpeg", "-hide_banner", "-nostdin", "-y",
                    "-i", str(src), "-i", str(wav_out),
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", acodec,
                    "-b:a", audio_bitrate_arg(info, 192000)]
            if suffix in _FASTSTART_EXT:
                argv += ["-movflags", "+faststart"]
            argv.append(str(out))
            ctx.run_cmd(argv)
        else:
            ext = src.suffix.lower().lstrip(".") or "mp3"
            out = ctx.output_dir / f"{src.stem}-denoised.{ext}"
            argv = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(wav_out)]
            if ext in ("mp3", "aac", "m4a", "ogg", "opus", "wma"):
                argv += ["-b:a", audio_bitrate_arg(info, 192000)]
            argv.append(str(out))
            ctx.run_cmd(argv)

        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("denoising produced no output")
        guard_output_size(out, "denoised file")
        ctx.progress(1.0, "done")
