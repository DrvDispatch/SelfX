import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

import pikepdf
from app.services.workflow_actions import run_action_plan, validate_plan
from app.tools import image_optimize, transcript_export  # noqa: F401
from app.tools._media import probe
from app.tools.base import ToolContext, ToolError
from app.tools.pdf_organize import PdfOrganize
from app.tools.subtitle_cleanup import SubtitleCleanup
from app.tools.video_target_size import VideoTargetSize


def context(root: Path, source: Path, params: dict) -> ToolContext:
    workdir, output = root / "work", root / "output"
    workdir.mkdir()
    output.mkdir()
    return ToolContext(uuid4(), [source], params, workdir, output)


def sample_pdf(path: Path) -> None:
    with pikepdf.new() as pdf:
        for index in range(1, 5):
            pdf.add_blank_page(page_size=(200 * index, 200))
        with pdf.open_outline() as outline:
            outline.root.append(pikepdf.OutlineItem("Second page", 1))
        pdf.save(path)


class PdfOrganizeTests(TestCase):
    def test_select_remove_and_reorder_pages(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.pdf"
            sample_pdf(source)
            original = source.read_bytes()
            ctx = context(root, source, {"page_order": "4,1-3", "remove_pages": "2"})
            PdfOrganize().run(ctx)
            with pikepdf.open(ctx.output_dir / "input-organized.pdf") as result:
                self.assertEqual([int(page.MediaBox[2]) for page in result.pages], [800, 200, 600])
            self.assertEqual(source.read_bytes(), original)

    def test_reorder_keeps_unchanged_outline_targets(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.pdf"
            sample_pdf(source)
            ctx = context(root, source, {"page_order": "2,4,1,3"})
            PdfOrganize().run(ctx)
            with pikepdf.open(ctx.output_dir / "input-organized.pdf") as result, result.open_outline() as outline:
                self.assertEqual(int(result.pages[0].MediaBox[2]), 400)
                self.assertEqual(outline.root[0].destination[0].objgen, result.pages[0].obj.objgen)

    def test_refuses_empty_selection(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.pdf"
            sample_pdf(source)
            ctx = context(root, source, {"remove_pages": "1-4"})
            with self.assertRaisesRegex(ToolError, "at least one page"):
                PdfOrganize().run(ctx)
            self.assertEqual(list(ctx.output_dir.iterdir()), [])


class SubtitleCleanupTests(TestCase):
    def test_decodes_utf16_sorts_deduplicates_and_clamps(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.srt"
            source.write_bytes((
                "4\r\n00:00:03,000 --> 00:00:04,000\r\n  Café  \r\n\r\n"
                "2\r\n00:00:00,250 --> 00:00:01,500\r\n Bonjour \r\n\r\n"
                "8\r\n00:00:03,000 --> 00:00:04,000\r\nCafé\r\n"
            ).encode("utf-16"))
            ctx = context(root, source, {"offset_ms": -500})
            SubtitleCleanup().run(ctx)
            actual = (ctx.output_dir / "input-cleaned.srt").read_text(encoding="utf-8")
            self.assertEqual(
                actual,
                "1\n00:00:00,000 --> 00:00:01,000\nBonjour\n\n"
                "2\n00:00:02,500 --> 00:00:03,500\nCafé\n\n",
            )

    def test_keeps_vtt_headers_and_position_in_workflow(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.vtt"
            source.write_text(
                "WEBVTT Test\n\nNOTE A comment\n\n1\n00:01.000 --> 00:02.000 position:10%\nこんにちは\n",
                encoding="utf-8",
            )
            ctx = context(root, source, {})
            run_action_plan(ctx, {"steps": [{
                "id": "clean", "action": "subtitle-cleanup", "input": "source", "params": {"offset_ms": 1000},
            }]})
            text = (ctx.output_dir / "clean-subtitles.vtt").read_text(encoding="utf-8")
            self.assertEqual(text, "WEBVTT Test\n\nNOTE A comment\n\n1\n00:00:02.000 --> 00:00:03.000 position:10%\nこんにちは\n\n")

    def test_rejects_inverted_times_without_output(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.srt"
            source.write_text("1\n00:00:04,000 --> 00:00:03,000\nCaption\n", encoding="utf-8")
            ctx = context(root, source, {})
            with self.assertRaisesRegex(ToolError, "must end after"):
                SubtitleCleanup().run(ctx)
            self.assertEqual(list(ctx.output_dir.iterdir()), [])


class NewWorkflowActionTests(TestCase):
    def test_transcript_export_produces_both_role_bound_outputs(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "transcript.json"
            source.write_text(json.dumps({"segments": [{"start": 0, "end": 1.25, "text": "Edited words."}]}), "utf-8")
            ctx = context(root, source, {})
            run_action_plan(ctx, {"steps": [
                {"id": "edit", "action": "transcript-export", "input": "source", "params": {"title": "Edited transcript"}},
                {"id": "clean", "action": "subtitle-cleanup", "input": "edit.captions", "params": {"offset_ms": 750}},
            ]})
            self.assertEqual(
                {item.name for item in ctx.output_dir.iterdir()},
                {"edit-pdf.pdf", "edit-captions.srt", "clean-subtitles.srt"},
            )
            self.assertIn("00:00:00,750 --> 00:00:02,000", (ctx.output_dir / "clean-subtitles.srt").read_text("utf-8"))

    def test_image_target_size_requires_jpeg_or_webp(self):
        plan = {"steps": [{"id": "small", "action": "image-optimize", "input": "source", "params": {"target_kb": 100}}]}
        self.assertEqual(validate_plan(plan, "photo.jpg")["steps"][0]["params"]["target_kb"], 100)
        self.assertEqual(validate_plan(plan, "photo.webp")["steps"][0]["params"]["target_kb"], 100)
        with self.assertRaisesRegex(ToolError, "needs a JPEG or WebP"):
            validate_plan(plan, "photo.png")


class VideoTargetSizeTests(TestCase):
    def test_infeasible_budget_rejects_before_encoding(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.mp4"
            source.write_bytes(b"fixture")
            ctx = context(root, source, {"target_mb": 0.1})
            info = {"video": True, "duration": 1200, "video_duration": 1200, "width": 640, "height": 480, "audio": True}
            with (
                patch("app.tools.video_target_size.probe", return_value=info),
                self.assertRaisesRegex(ToolError, "size limit is too small"),
            ):
                VideoTargetSize().run(ctx)
            self.assertEqual(list(ctx.output_dir.iterdir()), [])

    @skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg and FFprobe")
    def test_real_output_fits_limit_and_keeps_complete_video(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                "-t", "8", "-c:v", "libx264", "-crf", "13", "-c:a", "aac", str(source),
            ], capture_output=True, check=True, timeout=30)
            ctx = context(root, source, {"target_mb": 0.15})
            self.assertGreater(source.stat().st_size, 150_000)
            VideoTargetSize().run(ctx)
            result = ctx.output_dir / "input-compressed.mp4"
            self.assertLessEqual(result.stat().st_size, 150_000)
            info = probe(ctx, result)
            self.assertTrue(info["audio"])
            self.assertTrue(info["video"])
            self.assertGreaterEqual(info["video_duration"], 7.75)
