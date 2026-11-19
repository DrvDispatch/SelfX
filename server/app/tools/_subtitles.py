"""Shared helpers for the subtitle tools (convert / extract / sync).

Two real-world problems these address:
  * Legacy subs are frequently NOT UTF-8 (CP1256 Arabic, CP1251 Cyrillic,
    GBK/Big5, Shift-JIS, Latin-1, UTF-16/BOM). We detect the charset and can
    normalize the text to clean UTF-8 before handing it to ffmpeg/ffsubsync.
  * Success must mean ">=1 real cue", not just ">0 bytes" — a header-only
    ``WEBVTT\\n\\n`` or a zero-cue extract is a failure, not a success.

Dependency-light: charset detection uses charset-normalizer when present
(a transitive dependency) but degrades gracefully if it is missing.
"""

from pathlib import Path

from .base import ToolError

# Codecs that are effectively already UTF-8 / ASCII and need no rewrite.
_UTF8_ALIASES = {"utf-8", "utf_8", "utf8", "ascii", "us-ascii"}

# ffmpeg subtitle codecs that are IMAGE-based (bitmap) and cannot be muxed to a
# text format like SRT — they need OCR, not extraction.
IMAGE_SUB_CODECS = {
    "hdmv_pgs_subtitle",  # Blu-ray PGS
    "pgssub",
    "dvd_subtitle",       # DVD VobSub
    "dvdsub",
    "dvb_subtitle",       # DVB bitmap
    "dvbsub",
    "xsub",               # DivX bitmap subs
}


def detect_encoding(path: Path, sample_bytes: int = 262144) -> str | None:
    """Best-effort charset detection. Returns a Python codec name (e.g. 'cp1256',
    'utf-16') or None if it can't be determined. Never raises."""
    try:
        with path.open("rb") as subtitle_file:
            raw = subtitle_file.read(sample_bytes)
    except Exception:
        return None
    if not raw:
        return None
    # BOM sniffing is the most reliable signal — check it first.
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    # Fast path: valid strict UTF-8 needs no detection library.
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes
    except Exception:
        return None
    try:
        best = from_bytes(raw).best()
    except Exception:
        return None
    if best is None:
        return None
    enc = (best.encoding or "").lower()
    return enc or None


def normalize_to_utf8(path: Path, workdir: Path, override: str | None = None) -> Path:
    """Return a path to a UTF-8 copy of the subtitle text file.

    If the input is already UTF-8/ASCII (and has no BOM) the original path is
    returned unchanged. Otherwise the text is decoded with the detected (or
    caller-supplied) encoding and rewritten as UTF-8 into ``workdir``. On any
    failure the original path is returned so downstream tools still get a shot.
    """
    enc = override or detect_encoding(path)
    if enc is None:
        return path
    if enc.lower() in _UTF8_ALIASES:
        return path
    try:
        raw = path.read_bytes()
        text = raw.decode(enc, errors="replace")
    except (LookupError, OSError, ValueError):
        return path
    # Strip a leftover BOM so it doesn't leak into the first cue.
    if text and text[0] == "﻿":
        text = text[1:]
    out = workdir / f"{path.stem}.utf8{path.suffix or '.srt'}"
    try:
        out.write_text(text, encoding="utf-8")
    except OSError:
        return path
    return out


def looks_like_text_subtitle(path: Path) -> bool:
    """Cheap binary-vs-text sniff so a binary file renamed .srt fails fast with a
    clean message instead of a raw ffmpeg stderr tail."""
    try:
        chunk = path.read_bytes()[:8192]
    except Exception:
        return True  # let the engine decide
    if not chunk:
        return True
    # UTF-16 legitimately contains NUL bytes — allow it when a BOM is present.
    if chunk.startswith((b"\xff\xfe", b"\xfe\xff")):
        return True
    if b"\x00" in chunk:
        return False
    return True


def count_cues(path: Path) -> int:
    """Count subtitle cues without a parser library.

    ASS/SSA -> number of ``Dialogue:`` lines; SRT/VTT -> number of ``-->`` timing
    arrows. A header-only ``WEBVTT`` or an empty SRT therefore counts as 0.
    """
    try:
        raw = path.read_bytes()
    except Exception:
        return 0
    text = None
    for enc in ("utf-8-sig", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("latin-1", errors="replace")
    # ASS/SSA dialogue events.
    dialogue = text.count("\nDialogue:")
    if text.startswith("Dialogue:"):
        dialogue += 1
    if dialogue:
        return dialogue
    # SRT / VTT cue timing lines.
    return text.count("-->")


def validate_has_cues(path: Path) -> None:
    """Raise ToolError unless the output subtitle has at least one real cue."""
    if not path.is_file() or path.stat().st_size == 0:
        raise ToolError("no subtitles were produced — the input may be empty or malformed")
    if count_cues(path) < 1:
        raise ToolError(
            "the result had no subtitle cues (only an empty header) — "
            "the source may contain no actual subtitles"
        )
