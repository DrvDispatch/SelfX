import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from app.services import workflow_planner
from fastapi import HTTPException

_CATALOG = [
    {
        "slug": "transcript-pdf",
        "description": "Transcribe media and export PDF and captions.",
        "input_extensions": [".mp4"],
        "outputs": [{"role": "pdf", "extensions": [".pdf"]}],
        "params_schema": {"type": "object", "properties": {"language": {"type": "string"}}},
    },
    {
        "slug": "pdf-compress",
        "description": "Compress a PDF.",
        "input_extensions": [".pdf"],
        "outputs": [{"role": "result", "extensions": [".pdf"]}],
        "params_schema": {"type": "object"},
    },
]


class WorkflowPlannerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = SimpleNamespace(
            selfx_planner_model="qwen3.5:9b",
            selfx_planner_num_ctx=8192,
            ollama_url="http://ollama:11434",
            ollama_keep_alive="30s",
        )
        settings_patch = patch.object(workflow_planner, "settings", self.settings)
        settings_patch.start()
        self.addCleanup(settings_patch.stop)

    def client_with(self, handler):
        return patch.object(
            workflow_planner,
            "_client",
            side_effect=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

    async def test_planner_disabled_without_configured_model(self):
        self.settings.selfx_planner_model = ""
        with patch.object(workflow_planner, "_client") as client:
            self.assertEqual(await workflow_planner.planner_status(), {"available": False, "model": None})
            with self.assertRaises(HTTPException) as error:
                await workflow_planner.plan_prompt("Transcribe this video", ".mp4", _CATALOG)
        self.assertEqual(error.exception.status_code, 503)
        client.assert_not_called()

    async def test_status_requires_exact_local_model(self):
        remote_or_other_models = [
            {"name": "qwen3.5:9b-q4"},
            {"name": "qwen3.5:9b", "remote_model": "remote-forwarded"},
        ]
        with self.client_with(lambda req: httpx.Response(200, json={"models": remote_or_other_models})):
            self.assertEqual(
                await workflow_planner.planner_status(),
                {"available": False, "model": "qwen3.5:9b"},
            )
        self.settings.selfx_planner_model = "local-qwen"
        with self.client_with(lambda req: httpx.Response(200, json={"models": [{"model": "local-qwen:latest"}]})):
            self.assertTrue((await workflow_planner.planner_status())["available"])

    async def test_proposes_a_typed_multistep_draft_without_tool_execution(self):
        steps = [
            {"id": "transcribe", "action": "transcript-pdf", "input": "source", "params": {"language": "nl"}},
            {"id": "compress", "action": "pdf-compress", "input": "transcribe.pdf", "params": {}},
        ]
        prompt = "Transcribe the Dutch recording into a PDF, then compress the PDF."
        requests = []

        def handler(request):
            requests.append((request.method, request.url.path))
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"model": "qwen3.5:9b"}]})
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "qwen3.5:9b")
            self.assertEqual(payload["messages"][1], {"role": "user", "content": prompt})
            self.assertIn('"source_type":".mp4"', payload["messages"][0]["content"])
            self.assertFalse(payload["stream"])
            self.assertFalse(payload["think"])
            self.assertNotIn("tools", payload)
            self.assertEqual(payload["options"]["num_ctx"], 8192)
            self.assertEqual(
                payload["format"]["$defs"]["_PlannerStep"]["properties"]["action"]["enum"],
                ["pdf-compress", "transcript-pdf"],
            )
            return httpx.Response(200, json={
                "done": True, "message": {"content": json.dumps({"supported": True, "steps": steps})},
            })

        with self.client_with(handler):
            self.assertEqual(await workflow_planner.plan_prompt(prompt, ".mp4", _CATALOG), {"steps": steps})
        self.assertEqual(requests, [("GET", "/api/tags"), ("POST", "/api/chat")])

    async def test_unknown_or_unsupported_operations_are_rejected(self):
        for draft in (
            {"supported": False, "steps": []},
            {"supported": True, "steps": [
                {"id": "draft", "action": "unlisted-action", "input": "source", "params": {}},
            ]},
        ):
            def handler(request, result=draft):
                if request.url.path == "/api/tags":
                    return httpx.Response(200, json={"models": [{"model": "qwen3.5:9b"}]})
                return httpx.Response(200, json={
                    "done": True, "message": {"content": json.dumps(result)},
                })

            with self.client_with(handler), self.assertRaises(HTTPException) as error:
                await workflow_planner.plan_prompt("Try to do an unsupported operation.", ".mp4", _CATALOG)
            self.assertEqual(error.exception.status_code, 422)

    async def test_provider_errors_return_a_generic_error(self):
        def handler(request):
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"model": "qwen3.5:9b"}]})
            return httpx.Response(502, text="backend diagnostics")

        with self.client_with(handler), self.assertRaises(HTTPException) as error:
            await workflow_planner.plan_prompt("Transcribe this video", ".mp4", _CATALOG)
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("backend diagnostics", error.exception.detail)
