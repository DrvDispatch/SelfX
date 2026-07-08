"""media-download: fetch a video or audio track from a URL with yt-dlp.

Note: downloading from some sites may violate their Terms of Service — this is a
user-responsibility feature. Only http(s) URLs are accepted.
"""

from ._media import max_output_bytes
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
            "audio_codec": {
                "type": "string",
                "title": "Audio codec",
                "description": "Only for audio downloads. 'best' keeps the native "
                               "stream with no transcode (fastest, best quality).",
                "enum": ["mp3", "m4a", "opus", "best"],
                "default": "mp3",
            },
            "max_height": {
                "type": "integer",
                "title": "Max video height (px)",
                "description": "Cap resolution (e.g. 1080 or 720). Leave blank for best available.",
                "minimum": 144,
                "maximum": 4320,
            },
            "concurrent_fragments": {
                "type": "integer",
                "title": "Parallel fragments",
                "description": "Download this many HLS/DASH fragments at once (faster on "
                               "segmented streams). Output is identical.",
                "minimum": 1,
                "maximum": 16,
                "default": 4,
            },
            "subtitles": {
                "type": "boolean",
                "title": "Download & embed subtitles",
                "description": "Fetch available subtitles and embed them into the video.",
                "default": False,
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

        size_cap = max_output_bytes()

        def _hook(d: dict) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                got = d.get("downloaded_bytes") or 0
                # abort a runaway download early instead of filling the disk
                if got and got > size_cap:
                    raise ToolError(
                        f"the download exceeded the {size_cap // (1024 * 1024)} MB limit"
                    )
                if total:
                    ctx.progress(0.2 + 0.7 * min(1.0, got / total), "downloading")
            elif d.get("status") == "finished":
                ctx.progress(0.92, "processing")

        concurrent = self._clamp_int(ctx.params.get("concurrent_fragments"), 1, 16, 4)
        opts = {
            "outtmpl": str(ctx.workdir / "%(title).80s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "noprogress": True,
            # bound time and disk: cap size, time out idle sockets, limit retries
            "max_filesize": size_cap,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            # parallelise segmented (HLS/DASH) downloads; identical output, faster.
            "concurrent_fragment_downloads": concurrent,
            "progress_hooks": [_hook],
        }
        want_subs = bool(ctx.params.get("subtitles", False))
        if mode == "audio":
            audio_codec = str(ctx.params.get("audio_codec", "mp3"))
            opts["format"] = "bestaudio/best"
            if audio_codec != "best":
                # 'best' keeps the native audio stream — skip the transcode entirely.
                opts["postprocessors"] = [
                    {"key": "FFmpegExtractAudio", "preferredcodec": audio_codec}
                ]
        else:
            max_height = self._clamp_int(ctx.params.get("max_height"), 144, 4320, None)
            if max_height is not None:
                opts["format"] = (
                    f"bestvideo[height<=?{max_height}]+bestaudio/"
                    f"best[height<=?{max_height}]/best"
                )
            else:
                opts["format"] = "bestvideo*+bestaudio/best"
            opts["merge_output_format"] = "mp4"
            if want_subs:
                opts["writesubtitles"] = True
                opts["writeautomaticsub"] = True
                opts["subtitleslangs"] = ["en.*", "en"]
                opts["postprocessors"] = [{"key": "FFmpegEmbedSubtitle"}]

        ctx.progress(0.2, "downloading")
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if isinstance(info, dict) and info.get("is_live"):
                    raise ToolError(
                        "live streams can't be downloaded — wait until the stream has ended"
                    )
                ydl.process_ie_result(info, download=True)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - yt-dlp raises many types
            msg = str(exc).splitlines()[-1][:200] if str(exc) else "download failed"
            raise ToolError(f"could not download: {msg}") from None

        moved = 0
        total_bytes = 0
        for p in sorted(ctx.workdir.iterdir()):
            if p.is_file():
                total_bytes += p.stat().st_size
                p.replace(ctx.output_dir / p.name)
                moved += 1
        if moved == 0:
            raise ToolError("nothing was downloaded from that URL")
        if total_bytes > size_cap:
            for p in ctx.output_dir.iterdir():
                if p.is_file():
                    try:
                        p.unlink()
                    except OSError:
                        pass
            raise ToolError(
                f"the download is larger than the {size_cap // (1024 * 1024)} MB limit"
            )
        ctx.progress(1.0, "done")

    @staticmethod
    def _clamp_int(value, lo: int, hi: int, default):
        try:
            if value in (None, ""):
                return default
            return max(lo, min(hi, int(value)))
        except (TypeError, ValueError):
            return default
