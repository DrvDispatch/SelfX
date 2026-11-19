import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from app.tools._transcript_pdf import (
    build_transcript,
    export_transcript_pdf,
    run_transcript_pdf,
)
from app.tools.base import ToolContext
from app.tools.transcribe import Transcribe
from pypdf import PdfReader


class TranscriptPdfTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workdir = Path(temporary.name)
        self.output_dir = self.workdir / "out"
        self.output_dir.mkdir()
        self.progress = []
        self.ctx = ToolContext(
            uuid4(),
            [self.workdir / "stored-filename.mp4"],
            {"language": "nl", "source_name": "Les 1.mp4"},
            self.workdir,
            self.output_dir,
            lambda fraction, message: self.progress.append(fraction),
        )

    def test_recipe_exports_three_artifacts_from_one_inference(self):
        segments = [
            SimpleNamespace(start=0.0, end=1.25, text=" Café & één <voorbeeld>. "),
            SimpleNamespace(start=1.25, end=2.5, text="Dit is de tweede zin."),
        ]
        with (
            patch("app.tools.transcribe.probe", return_value={"audio": True, "video": True, "duration": 2.5}),
            patch.object(Transcribe, "_run_faster_whisper", return_value=(segments, "nl", 2.5)) as infer,
        ):
            run_transcript_pdf(self.ctx)
            self.assertEqual(infer.call_count, 1)
            self.assertEqual(infer.call_args.args[3:5], ("nl", "transcribe"))

        self.assertEqual(
            {file.name for file in self.output_dir.iterdir()},
            {"captions.srt", "transcript.json", "transcript.pdf"},
        )
        captions = (self.output_dir / "captions.srt").read_text("utf-8")
        self.assertIn("00:00:00,000 --> 00:00:01,250\nCafé & één <voorbeeld>.", captions)
        transcript = json.loads((self.output_dir / "transcript.json").read_text("utf-8"))
        self.assertEqual(transcript["schema_version"], 1)
        self.assertEqual(transcript["language"], "nl")
        self.assertEqual(transcript["segments"][1]["start"], 1.25)
        pdf = PdfReader(self.output_dir / "transcript.pdf")
        content = pdf.pages[0].extract_text()
        self.assertIn("Les 1", content)
        self.assertIn("Café & één <voorbeeld>.", content)
        self.assertIn("00:00:01", content)
        self.assertEqual(self.progress, sorted(self.progress))

    def test_export_of_checkpoint_paginates_without_inference(self):
        self.ctx.params["title"] = "Lange opname"
        transcript = {
            "schema_version": 1,
            "engine": "faster-whisper",
            "language": "nl",
            "duration": 120,
            "segments": [
                {"start": i, "end": i + 1, "text": f"Fragment {i}. " + "Korte tekst. " * 10}
                for i in range(120)
            ],
        }
        with patch.object(Transcribe, "transcribe", side_effect=AssertionError("Unexpected inference")):
            export_transcript_pdf(self.ctx, transcript)

        pdf = PdfReader(self.output_dir / "transcript.pdf")
        self.assertGreater(len(pdf.pages), 1)
        self.assertEqual(pdf.metadata.title, "Lange opname")
        self.assertIn("Fragment 119.", pdf.pages[-1].extract_text())

    def test_missing_glyphs_are_preserved_in_captions_and_json(self):
        text = "Voorbeeld \U0010fffd einde"
        transcript = {
            "language": "nl",
            "duration": 1.5,
            "segments": [{"start": 0, "end": 1.5, "text": text}],
        }
        export_transcript_pdf(self.ctx, transcript)
        pdf = PdfReader(self.output_dir / "transcript.pdf")
        self.assertIn("characters missing from the PDF font", pdf.pages[0].extract_text())
        self.assertIn(text, (self.output_dir / "captions.srt").read_text("utf-8"))
        payload = json.loads((self.output_dir / "transcript.json").read_text("utf-8"))
        self.assertEqual(payload["segments"][0]["text"], text)

    def test_build_leaves_export_to_the_export_stage(self):
        result = {
            "language": "nl",
            "duration": 1,
            "segments": [{"start": 0, "end": 1, "text": "Hallo."}],
        }
        with patch.object(Transcribe, "transcribe", return_value=result):
            transcript = build_transcript(self.ctx)
        self.assertEqual(transcript["engine"], "faster-whisper")
        self.assertEqual(list(self.output_dir.iterdir()), [])
