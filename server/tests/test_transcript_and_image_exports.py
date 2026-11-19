import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from PIL import Image
from pypdf import PdfReader

from app.tools.base import ToolContext, ToolError
from app.tools.image_optimize import ImageOptimize
from app.tools.transcript_export import TranscriptExport


class ExportTests(TestCase):
    def make_context(self, source: Path, params: dict) -> ToolContext:
        outputs = source.parent / "exports"
        outputs.mkdir(exist_ok=True)
        return ToolContext(uuid4(), [source], params, source.parent, outputs)

    def test_edited_transcript_exports_pdf_and_clean_captions(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "edited.json"
            source.write_text(json.dumps({
                "language": "nl",
                "segments": [{"start": 0.25, "end": 1.75, "text": "Tekst aangepast.\n\nTweede regel."}],
            }), encoding="utf-8")
            ctx = self.make_context(source, {"title": "Lessen"})
            TranscriptExport().run(ctx)
            pdf = PdfReader(ctx.output_dir / "transcript.pdf")
            self.assertIn("Tekst aangepast.", pdf.pages[0].extract_text())
            captions = (ctx.output_dir / "captions.srt").read_text("utf-8")
            self.assertIn("00:00:00,250 --> 00:00:01,750", captions)
            self.assertIn("aangepast.\nTweede", captions)

    def test_bad_timing_fails_before_pdf_creation(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "edited.json"
            source.write_text(json.dumps({
                "segments": [{"start": 2, "end": 1, "text": "Timing mistake"}],
            }), encoding="utf-8")
            ctx = self.make_context(source, {})
            with self.assertRaisesRegex(ToolError, "invalid timing"):
                TranscriptExport().run(ctx)
            self.assertFalse(list(ctx.output_dir.iterdir()))

    def test_target_size_fails_for_unreachable_limit(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "noise.jpg"
            with Image.effect_noise((500, 500), 60) as fixture:
                fixture.save(source, quality=95)
            ctx = self.make_context(source, {"target_kb": 1})
            with self.assertRaisesRegex(ToolError, "cannot fit"):
                ImageOptimize().run(ctx)
            self.assertFalse(list(ctx.output_dir.iterdir()))

    def test_target_size_exports_measured_bytes(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "noise.jpg"
            with Image.effect_noise((500, 500), 60) as fixture:
                fixture.save(source, quality=95)
            ctx = self.make_context(source, {"target_kb": 32})
            ImageOptimize().run(ctx)
            output, = ctx.output_dir.iterdir()
            self.assertLessEqual(output.stat().st_size, 32 * 1024)
            self.assertLess(output.stat().st_size, source.stat().st_size)
