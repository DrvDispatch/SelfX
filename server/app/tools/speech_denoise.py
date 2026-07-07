"""speech-denoise: remove steady background noise (fan, A/C, ventilator, hiss) from
audio OR video, keeping the video stream and choosing how aggressively to clean.

Uses spectral-gating noise reduction (noisereduce), which is strongest exactly on
constant broadband noise like fans/ventilators. For a video input the original video
is kept and only its audio is cleaned; for audio the original format is preserved.
"""

from .base import Tool, ToolContext, ToolError
from .registry import register

_VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".flv", ".wmv"}

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
            }
        },
    }

    def run(self, ctx: ToolContext) -> None:
        import noisereduce as nr
        import numpy as np
        from scipy.io import wavfile

        strength = str(ctx.params.get("strength", "strong"))
        prop = _STRENGTH.get(strength, 0.9)
        src = ctx.input_paths[0]
        is_video = src.suffix.lower() in _VIDEO_EXT

        # 1) decode the audio track to WAV (preserving sample rate + channels)
        wav_in = ctx.workdir / "audio.wav"
        ctx.progress(0.15, "decoding audio")
        ctx.run_cmd(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
                     "-vn", "-c:a", "pcm_s16le", str(wav_in)])
        sr, data = wavfile.read(str(wav_in))

        # 2) normalise to float, reduce noise per channel
        if data.dtype == np.int16:
            y = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            y = data.astype(np.float32) / 2147483648.0
        elif data.dtype == np.uint8:
            y = (data.astype(np.float32) - 128.0) / 128.0
        else:
            y = data.astype(np.float32)

        ctx.progress(0.45, f"removing background noise ({strength})")
        if y.ndim == 1:
            cleaned = nr.reduce_noise(y=y, sr=sr, stationary=True, prop_decrease=prop)
        else:  # (samples, channels) -> clean each channel
            chans = [nr.reduce_noise(y=y[:, c], sr=sr, stationary=True, prop_decrease=prop)
                     for c in range(y.shape[1])]
            cleaned = np.stack(chans, axis=1)
        wav_out = ctx.workdir / "clean.wav"
        wavfile.write(str(wav_out), sr, (np.clip(cleaned, -1.0, 1.0) * 32767).astype(np.int16))

        # 3) rebuild the output: remux cleaned audio into the video, or re-encode audio
        ctx.progress(0.8, "writing output")
        if is_video:
            out = ctx.output_dir / f"{src.stem}-denoised.mp4"
            ctx.run_cmd(["ffmpeg", "-hide_banner", "-nostdin", "-y",
                         "-i", str(src), "-i", str(wav_out),
                         "-map", "0:v:0", "-map", "1:a:0",
                         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                         "-movflags", "+faststart", str(out)])
        else:
            ext = src.suffix.lower().lstrip(".") or "mp3"
            out = ctx.output_dir / f"{src.stem}-denoised.{ext}"
            ctx.run_cmd(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(wav_out), str(out)])

        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("denoising produced no output")
        ctx.progress(1.0, "done")
