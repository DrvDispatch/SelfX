"""video-concat: join several clips into one (FFmpeg).

Clips may differ in size/codec/framerate, so each is first normalised to a common
format (scaled + padded to the first clip's resolution, 30 fps, h264 + aac 48 kHz
stereo, with silent audio synthesised for clips that have none), then losslessly
concatenated with the concat demuxer.
"""

from ._media import guard_output_size, probe
from .base import Tool, ToolContext, ToolError
from .registry import register

_VIDEO = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg"]


@register
class VideoConcat(Tool):
    slug = "video-concat"
    name = "Join videos"
    category = "media"
    description = "Concatenate several clips into one video (they can differ in size/format — order matters)."
    accepts = _VIDEO
    multi_file = True
    min_files = 2
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "fps": {"type": "integer", "title": "Frame rate", "enum": [24, 25, 30, 50, 60], "default": 30},
        },
    }

    def run(self, ctx: ToolContext) -> None:
        srcs = ctx.input_paths
        fps = int(ctx.params.get("fps", 30) or 30)

        first = probe(ctx, srcs[0])
        w = first["width"] or 1280
        h = first["height"] or 720
        w -= w % 2
        h -= h % 2

        normalized = []
        total = len(srcs)
        for i, src in enumerate(srcs):
            ctx.progress(0.05 + 0.8 * i / total, f"preparing clip {i + 1}/{total}")
            norm = ctx.workdir / f"norm_{i:03d}.mp4"
            vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                  f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps}")
            argv = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src)]
            if probe(ctx, src)["audio"]:
                argv += ["-vf", vf, "-map", "0:v:0", "-map", "0:a:0?"]
            else:
                # synthesise silent stereo audio so every clip has an audio track
                argv += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                         "-vf", vf, "-map", "0:v:0", "-map", "1:a", "-shortest"]
            argv += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                     "-c:a", "aac", "-ar", "48000", "-ac", "2", str(norm)]
            ctx.run_cmd(argv)
            if not norm.is_file() or norm.stat().st_size == 0:
                raise ToolError(f"could not prepare clip {i + 1} for joining")
            normalized.append(norm)

        list_file = ctx.workdir / "concat.txt"
        list_file.write_text("".join(f"file '{p}'\n" for p in normalized), encoding="utf-8")

        out = ctx.output_dir / "joined.mp4"
        ctx.progress(0.9, "joining")
        ctx.run_cmd([
            "ffmpeg", "-hide_banner", "-nostdin", "-y",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", "-movflags", "+faststart", str(out),
        ])
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("joining the clips failed")
        guard_output_size(out, "joined video")
        ctx.progress(1.0, "done")
