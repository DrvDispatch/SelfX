"""Build once with local Whisper, then export a PDF and subtitle bundle."""

from functools import cache
from pathlib import Path
from unicodedata import normalize
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate

from .base import ToolContext, ToolError
from .transcribe import Transcribe, _ts, write_transcript


def build_transcript(ctx: ToolContext) -> dict:
    """Use the configured faster-whisper engine once and return JSON-ready data."""
    if len(ctx.input_paths) != 1:
        raise ToolError("transcription needs one audio or video file")

    inference = ToolContext(
        job_id=ctx.job_id,
        input_paths=ctx.input_paths,
        params={"language": ctx.params.get("language") or "auto"},
        workdir=ctx.workdir,
        output_dir=ctx.output_dir,
        progress_cb=lambda fraction, message: ctx.progress(min(0.85, fraction * 0.9), message),
    )
    transcript = Transcribe().transcribe(inference)
    ctx.progress(0.86, "transcript ready")
    return {"schema_version": 1, "engine": "faster-whisper", **transcript}


@cache
def _pdf_font() -> TTFont:
    # The packaged worker uses DejaVu Sans (Latin, Greek and Cyrillic).
    # A direct install can also use the system Arial or ReportLab's Latin font.
    candidates = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path(reportlab.__file__).with_name("fonts") / "Vera.ttf",
    )
    for path in candidates:
        if path.is_file():
            font = TTFont("SelfXTranscript", str(path))
            pdfmetrics.registerFont(font)
            return font
    raise ToolError("no font is installed for transcript PDF export")


def _write_pdf(path: Path, title: str, transcript: dict) -> None:
    font = _pdf_font()
    ink = HexColor("#172620")
    muted = HexColor("#4C6259")
    glyphs = font.face.charToGlyph
    replacement = "\ufffd" if ord("\ufffd") in glyphs else "?"
    substituted = False

    def pdf_text(value: str) -> str:
        nonlocal substituted
        visible = []
        for char in normalize("NFC", value):
            if char.isspace():
                visible.append("\n" if char == "\n" else " ")
            elif ord(char) in glyphs:
                visible.append(char)
            else:
                visible.append(replacement)
                substituted = True
        # Paragraph accepts markup. Escape source text before adding our line breaks.
        return escape("".join(visible)).replace("\n", "<br/>")

    body = ParagraphStyle(
        "TranscriptBody", fontName=font.fontName, fontSize=11,
        leading=16, textColor=ink, spaceAfter=9,
    )
    heading = ParagraphStyle(
        "TranscriptTitle", parent=body, fontSize=22, leading=27,
    )
    detail = ParagraphStyle(
        "TranscriptMeta", parent=body, fontSize=9, leading=13,
        textColor=muted, spaceAfter=16,
    )

    summary = []
    if transcript.get("language"):
        summary.append(f"Language {transcript['language']}")
    if transcript.get("duration"):
        duration = _ts(transcript["duration"], ".").split(".")[0]
        summary.append(f"Duration {duration}")

    story = [Paragraph(pdf_text(title), heading)]
    if summary:
        story.append(Paragraph(pdf_text("  ·  ".join(summary)), detail))
    for segment in transcript["segments"]:
        timestamp = _ts(segment["start"] or 0, ".").split(".")[0]
        text = pdf_text(segment["text"])
        story.append(
            Paragraph(f'<font color="#4C6259" size="9">{timestamp}</font> &nbsp; {text}', body)
        )
    if substituted:
        story.append(Paragraph("The subtitle and JSON files preserve characters missing from the PDF font.", detail))

    doc = SimpleDocTemplate(
        str(path), pagesize=A4, title=title, leftMargin=54, rightMargin=54,
        topMargin=54, bottomMargin=54, pageCompression=1,
    )

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font.fontName, 9)
        canvas.setFillColor(muted)
        canvas.drawRightString(A4[0] - 54, 30, str(document.page))
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def export_transcript_pdf(ctx: ToolContext, transcript: dict, *, include_json: bool = True) -> None:
    """Render PDF, SRT and timed JSON from a built transcript without inference."""
    title = str(ctx.params.get("title") or "").strip()
    if not title:
        source = str(ctx.params.get("source_name") or "").strip()
        title = Path(source).stem or "Transcript"

    ctx.progress(0.88, "formatting transcript PDF")
    _write_pdf(ctx.output_dir / "transcript.pdf", title, transcript)
    ctx.progress(0.95, "exporting captions")
    write_transcript(ctx.output_dir / "captions.srt", "srt", transcript)
    if include_json:
        write_transcript(ctx.output_dir / "transcript.json", "json", transcript)
    ctx.progress(0.97, "transcript exports ready")


def run_transcript_pdf(ctx: ToolContext) -> None:
    export_transcript_pdf(ctx, build_transcript(ctx))
