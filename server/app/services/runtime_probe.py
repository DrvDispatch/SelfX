"""Read-only resource estimates for the API process hosting the setup panel."""

import os
import platform
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import psutil

from ..config import settings

_CGROUP_ROOT = Path("/sys/fs/cgroup")
_CGROUP_MEMBERSHIP = Path("/proc/self/cgroup")
_GIB = 1024**3
_MIB = 1024**2


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def _cgroup_ancestors() -> Iterator[Path]:
    for line in _read(_CGROUP_MEMBERSHIP).splitlines():
        if not line.startswith("0::/"):
            continue
        group = Path(line[4:])
        if group.is_absolute() or ".." in group.parts:
            break
        path = _CGROUP_ROOT / group
        if path.is_dir():
            while path != _CGROUP_ROOT:
                yield path
                path = path.parent
        break
    yield _CGROUP_ROOT


def _integer(value: str) -> int | None:
    try:
        number = int(value)
    except ValueError:
        return None
    return number if number >= 0 else None


def _resources(os_name: str) -> tuple[float, int | None, int | None]:
    cores = float(os.cpu_count() or 1)
    try:
        affinity = psutil.Process().cpu_affinity()
    except (AttributeError, NotImplementedError, OSError, psutil.Error):
        affinity = []
    if affinity:
        cores = min(cores, len(affinity))

    total = None
    available = None
    try:
        memory = psutil.virtual_memory()
        total, available = memory.total, memory.available
    except (NotImplementedError, OSError, psutil.Error):
        pass

    if os_name == "Linux":
        for path in _cgroup_ancestors():
            cpu = _read(path / "cpu.max").split()
            if len(cpu) == 2:
                quota, period = map(_integer, cpu)
                if quota and period:
                    cores = min(cores, quota / period)
            limit = _integer(_read(path / "memory.max"))
            if limit is not None:
                total = limit if total is None else min(total, limit)
                usage = _integer(_read(path / "memory.current"))
                if usage is not None:
                    free = max(0, limit - usage)
                    available = free if available is None else min(available, free)

    if total is not None and available is not None:
        available = min(available, total)
    return round(cores, 3), total, available


def _nvidia_memory() -> list[dict] | None:
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return None
    try:
        result = subprocess.run(
            [nvidia_smi, "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, encoding="ascii", errors="replace", timeout=2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    gpus = []
    for row in result.stdout.splitlines():
        values = row.split(",")
        if len(values) != 2:
            continue
        total, free = map(_integer, values)
        if total and free is not None and free <= total:
            gpus.append({"total_bytes": total * _MIB, "free_bytes": free * _MIB})
    return gpus or None


def _estimate(cores: float, available: int | None, gpus: list[dict] | None) -> dict:
    ram = (available or 0) / _GIB
    vram = max((gpu["free_bytes"] for gpu in gpus or []), default=0) / _GIB
    if vram >= 22 and ram >= 6:
        model, context = "qwen3.8:27b", 8192
    elif vram >= 10 and ram >= 5:
        model, context = "qwen3.5:9b", 16384
    elif (vram >= 5 and ram >= 5) or (cores >= 4 and ram >= 12):
        model, context = "qwen3.5:4b", 8192
    elif cores >= 2 and ram >= 6:
        model, context = "qwen3.5:2b", 4096
    else:
        model, context = None, None
    note = (
        "Estimated from currently visible memory and CPU capacity. Test on the model host before increasing context."
        if model
        else "Start with manual tools and recipes. Check the model host directly if it runs separately."
    )
    return {"kind": "estimate", "model": model, "context_tokens": context, "note": note}


def probe_hardware() -> dict:
    os_name = platform.system()
    cores, total, available = _resources(os_name)
    try:
        disk_free = shutil.disk_usage(settings.data_dir).free
    except OSError:
        disk_free = None
    gpus = _nvidia_memory()
    in_container = Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()
    return {
        "scope": "api_container" if in_container else "api_host",
        "scope_note": (
            "Values describe the API process. A separate worker or Ollama service may see different resources."
        ),
        "os": os_name,
        "architecture": platform.machine(),
        "effective_cpu_cores": cores,
        "memory_total_bytes": total,
        "memory_available_bytes": available,
        "disk_free_bytes": disk_free,
        "nvidia_gpus": gpus,
        "recommendation": _estimate(cores, available, gpus),
    }
