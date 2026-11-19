import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.auth import get_current_user
from app.routes import models
from app.services import runtime_probe
from fastapi import FastAPI
from fastapi.testclient import TestClient

_GIB = 1024**3


class RuntimeProbeTests(unittest.TestCase):
    def test_linux_cgroup_caps_affinity_and_hierarchical_headroom(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir) / "cgroup"
            group = root / "services" / "api"
            group.mkdir(parents=True)
            membership = Path(tempdir) / "membership"
            membership.write_text("0::/services/api\n", encoding="utf-8")
            snapshots = {
                root: ("max 100000", "max", "0"),
                group.parent: ("250000 100000", str(20 * _GIB), str(18 * _GIB)),
                group: ("150000 100000", str(8 * _GIB), str(3 * _GIB)),
            }
            for path, (cpu, limit, used) in snapshots.items():
                (path / "cpu.max").write_text(cpu, encoding="utf-8")
                (path / "memory.max").write_text(limit, encoding="utf-8")
                (path / "memory.current").write_text(used, encoding="utf-8")

            with (
                patch.object(runtime_probe, "_CGROUP_ROOT", root),
                patch.object(runtime_probe, "_CGROUP_MEMBERSHIP", membership),
                patch.object(runtime_probe.os, "cpu_count", return_value=16),
                patch.object(runtime_probe.psutil.Process, "cpu_affinity", return_value=list(range(4)), create=True),
                patch.object(
                    runtime_probe.psutil, "virtual_memory",
                    return_value=SimpleNamespace(total=64 * _GIB, available=32 * _GIB),
                ),
            ):
                self.assertEqual(runtime_probe._resources("Linux"), (1.5, 8 * _GIB, 2 * _GIB))

    def test_nvidia_query_is_bounded_and_reports_visible_memory_only(self):
        gpu_output = "12288, 11300\nN/A, N/A\n1000, 1001\n2048, 0\n"
        with (
            patch.object(runtime_probe.shutil, "which", return_value="nvidia-smi"),
            patch.object(runtime_probe.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout=gpu_output,
            )) as run,
        ):
            gpus = runtime_probe._nvidia_memory()
        mib = 1024**2
        self.assertEqual(gpus, [
            {"total_bytes": 12 * _GIB, "free_bytes": 11300 * mib},
            {"total_bytes": 2 * _GIB, "free_bytes": 0},
        ])
        self.assertEqual(run.call_args.kwargs["timeout"], 2)
        self.assertIn("--query-gpu=memory.total,memory.free", run.call_args.args[0])

        with (
            patch.object(runtime_probe.shutil, "which", return_value="nvidia-smi"),
            patch.object(runtime_probe.subprocess, "run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 2)),
        ):
            self.assertIsNone(runtime_probe._nvidia_memory())

    def test_recommendation_distinguishes_free_and_total_gpu_memory(self):
        low_free = [{"total_bytes": 24 * _GIB, "free_bytes": 2 * _GIB}]
        moderate_free = [{"total_bytes": 12 * _GIB, "free_bytes": 11 * _GIB}]
        self.assertEqual(runtime_probe._estimate(4, 8 * _GIB, moderate_free)["context_tokens"], 16384)
        self.assertEqual(runtime_probe._estimate(2, 6 * _GIB, low_free)["model"], "qwen3.5:2b")
        self.assertIsNone(runtime_probe._estimate(1, 2 * _GIB, None)["model"])

    def test_hardware_endpoint_requires_admin_and_disables_caching(self):
        app = FastAPI()
        app.include_router(models.router)
        probe = {"scope": "api_host"}
        with TestClient(app) as client, patch.object(models, "probe_hardware", return_value=probe) as collect:
            app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=False)
            self.assertEqual(client.get("/admin/models/hardware").status_code, 403)
            collect.assert_not_called()

            app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=True)
            response = client.get("/admin/models/hardware")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), probe)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            collect.assert_called_once()
