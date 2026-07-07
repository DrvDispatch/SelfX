"""Local agent brain: Ollama /api/chat tool-calling loop (fully offline, no key)."""

import json
import logging
import uuid

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import User
from . import core

logger = logging.getLogger("selfx.agent.ollama")
_MAX_STEPS = 6

_SYSTEM = (
    "You are SelfX's assistant. You help the user by calling tools that process their "
    "files locally. When a tool needs files, pass their ids in `file_ids` (use the "
    "Attached files list). Prefer a single tool call that accomplishes the request; "
    "after tools run, give a short, friendly summary of what you did and name the output "
    "files. If no tool fits, just answer normally."
)


def _ollama_tools(specs: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {"name": s["name"], "description": s["description"],
                                              "parameters": s["parameters"]}} for s in specs]


def run(db: Session, user: User, message: str, attached_file_ids: list[uuid.UUID],
        history: list[dict] | None = None) -> tuple[str, list[dict]]:
    specs = core.build_specs()
    tools = _ollama_tools(specs)
    manifest = core.file_manifest(db, user, attached_file_ids)
    sys = _SYSTEM
    if manifest:
        sys += "\n\nAttached files:\n" + "\n".join(f"- {f['name']} (id={f['id']}, type={f['type']})" for f in manifest)

    messages = [{"role": "system", "content": sys}]
    messages += history or []
    messages.append({"role": "user", "content": message})
    steps: list[dict] = []

    for _ in range(_MAX_STEPS):
        try:
            r = httpx.post(
                f"{settings.ollama_url}/api/chat",
                json={"model": settings.ollama_model, "messages": messages, "tools": tools,
                      "stream": False, "keep_alive": settings.ollama_keep_alive,
                      "options": {"num_ctx": settings.ollama_num_ctx}},
                timeout=httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=5.0),
            )
            r.raise_for_status()
            msg = r.json()["message"]
        except Exception as exc:  # noqa: BLE001
            logger.exception("ollama agent chat failed")
            return f"The local AI service failed: {exc}", steps

        calls = msg.get("tool_calls") or []
        if not calls:
            return (msg.get("content") or "").strip() or "(no response)", steps

        messages.append(msg)  # assistant turn carrying the tool_calls
        for tc in calls:
            fn = tc.get("function", {})
            nm = fn.get("name", "")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            result = core.dispatch(nm, args, db, user, attached_file_ids)
            steps.append({"tool": nm, "args": args, "result": result})
            messages.append({"role": "tool", "content": json.dumps(result)[:3000]})

    return "I couldn't finish that within a few steps — try rephrasing or doing it in parts.", steps
