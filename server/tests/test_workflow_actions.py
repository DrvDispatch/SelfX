from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from PIL import Image

from app.services.workflow_actions import run_action_plan, validate_plan
from app.tools import image_convert, image_optimize  # noqa: F401
from app.tools.base import ToolContext, ToolError


def image_plan() -> dict:
    return {"steps": [
        {"id": "convert", "action": "image-convert", "input": "source",
         "params": {"format": "jpg", "max_width": 16}},
        {"id": "optimize", "action": "image-optimize", "input": "convert.image", "params": {}},
    ]}


class WorkflowActionsTest(TestCase):
    def test_rejects_invalid_references_and_unknown_params(self) -> None:
        plan = image_plan()
        plan["steps"][1]["input"] = "convert.transcript"
        with self.assertRaises(ToolError):
            validate_plan(plan, "photo.png")
        plan = image_plan()
        plan["steps"][0]["params"]["unknown"] = True
        with self.assertRaises(ToolError):
            validate_plan(plan, "photo.png")

    def test_outputs_are_bound_by_role(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "photo.png"
            Image.new("RGB", (32, 24), "blue").save(source)
            ctx = ToolContext(uuid4(), [source], {}, root / "work", root / "output")
            run_action_plan(ctx, image_plan())
            self.assertEqual(
                {file.name for file in ctx.output_dir.iterdir()},
                {"convert-image.jpg", "optimize-image.jpg"},
            )
            with Image.open(ctx.output_dir / "optimize-image.jpg") as image:
                self.assertEqual(image.size, (16, 12))

    def test_artifacts_share_one_output_budget(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "photo.png"
            Image.new("RGB", (32, 24), "blue").save(source)
            ctx = ToolContext(uuid4(), [source], {}, root / "work", root / "output")
            with patch("app.services.workflow_actions._media.max_output_bytes", return_value=1):
                with self.assertRaisesRegex(ToolError, "output limit"):
                    run_action_plan(ctx, image_plan())
            self.assertEqual(list(ctx.output_dir.iterdir()), [])
