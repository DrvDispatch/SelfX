"""video-fade: add fade-in / fade-out to a video (and audio) (FFmpeg)."""

from ._media import guard_output_size, probe
from .base import Tool, ToolContext, ToolError
from .registry import register

_VIDEO = [".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg"]


@register
class VideoFade(Tool):
    slug = "video-fade"
    name = "Fade in / out"
    category = "media"
    description = "Add a fade-in at the start and/or a fade-out at the end (video and audio)."
    accepts = _VIDEO
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "fade_in": {"type": "number", "title": "Fade in (seconds)", "minimum": 0, "maximum": 60, "default": 1},
            "fade_out": {"type": "number", "title": "Fade out (seconds)", "minimum": 0, "maximum": 60, "default": 1},
            "color": {
                "type": "string",
                "title": "Fade colour",
                "enum": ["black", "white"],
                "default": "black",
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        try:
            fin = max(0.0, float(ctx.params.get("fade_in", 1)))
            fout = max(0.0, float(ctx.params.get("fade_out", 1)))
        except (TypeError, ValueError):
            raise ToolError("fade durations must be numbers") from None
        if fin == 0 and fout == 0:
            raise ToolError("set a fade-in and/or fade-out duration")
        color = "white" if str(ctx.params.get("color")) == "white" else "black"

        info = probe(ctx, src)
        dur = info["duration"] or 0.0
        if fout > 0 and dur <= 0:
            raise ToolError("could not read the video length — needed for the fade-out")
        out_start = max(0.0, dur - fout)

        vparts, aparts = [], []
        if fin > 0:
            vparts.append(f"fade=t=in:st=0:d={fin}:c={color}")
            aparts.append(f"afade=t=in:st=0:d={fin}")
        if fout > 0:
            vparts.append(f"fade=t=out:st={out_start}:d={fout}:c={color}")
            aparts.append(f"afade=t=out:st={out_start}:d={fout}")

        argv = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src), "-vf", ",".join(vparts)]
        if info["audio"]:
            argv += ["-af", ",".join(aparts), "-c:a", "aac"]
        argv += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-movflags", "+faststart",
                 str(ctx.output_dir / f"{src.stem}-fade.mp4")]

        ctx.progress(0.3, "adding fades")
        ctx.run_cmd(argv)
        out = ctx.output_dir / f"{src.stem}-fade.mp4"
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("fade failed — the file may not be a valid video")
        guard_output_size(out, "video")
        ctx.progress(1.0, "done")
