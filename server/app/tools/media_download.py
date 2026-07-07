"""media-download: fetch a video or audio track from a URL with yt-dlp.

Note: downloading from some sites may violate their Terms of Service — this is a
user-responsibility feature. Only http(s) URLs are accepted.
"""

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class MediaDownload(Tool):
    slug = "media-download"
    name = "Download from URL"
    category = "media"
    description = "Download a video or extract the audio from a media URL (YouTube, Vimeo, etc.)."
    accepts = []
    multi_file = False
    min_files = 0
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "title": "URL",
                "description": "Link to the video/audio page",
                "minLength": 8,
                "maxLength": 2000,
            },
            "format": {
                "type": "string",
                "title": "Download as",
                "enum": ["video", "audio"],
                "default": "video",
            },
        },
        "required": ["url"],
    }

    def run(self, ctx: ToolContext) -> None:
        import yt_dlp

        url = str(ctx.params["url"]).strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ToolError("please provide a valid http(s) URL")
        mode = str(ctx.params.get("format", "video"))

        opts = {
            "outtmpl": str(ctx.workdir / "%(title).80s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "noprogress": True,
        }
        if mode == "audio":
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
        else:
            opts["format"] = "bestvideo*+bestaudio/best"
            opts["merge_output_format"] = "mp4"

        ctx.progress(0.2, "downloading")
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
        except Exception as exc:  # noqa: BLE001 - yt-dlp raises many types
            msg = str(exc).splitlines()[-1][:200] if str(exc) else "download failed"
            raise ToolError(f"could not download: {msg}") from None

        moved = 0
        for p in sorted(ctx.workdir.iterdir()):
            if p.is_file():
                p.replace(ctx.output_dir / p.name)
                moved += 1
        if moved == 0:
            raise ToolError("nothing was downloaded from that URL")
        ctx.progress(1.0, "done")
