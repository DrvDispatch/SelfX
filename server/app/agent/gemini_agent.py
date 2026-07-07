"""Cloud agent brain: Gemini function-calling loop (google-genai), opt-in via GEMINI_API_KEY.

Automatic function calling is DISABLED — we intercept each FunctionCall and run it
through SelfX's own validated job pipeline locally, then hand the model back only a
small result summary. File bytes never go to Google."""

import logging
import os
import uuid

from sqlalchemy.orm import Session

from ..config import settings
from ..models import User
from . import core
from .ollama_agent import _SYSTEM

logger = logging.getLogger("selfx.agent.gemini")
_MAX_STEPS = 6


def available() -> bool:
    if settings.gemini_use_vertex:
        cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        return bool(settings.gemini_project) and bool(cred) and os.path.exists(cred)
    return bool(settings.gemini_api_key)


def _client():
    from google import genai

    if settings.gemini_use_vertex:
        # credentials picked up from GOOGLE_APPLICATION_CREDENTIALS (service account)
        return genai.Client(vertexai=True, project=settings.gemini_project, location=settings.gemini_location)
    return genai.Client(api_key=settings.gemini_api_key)


def _declarations(specs: list[dict]):
    from google.genai import types

    decls = []
    for s in specs:
        params = core.gemini_safe_schema(s["parameters"])
        # a no-arg function must omit parameters entirely for Gemini
        kwargs = {"name": s["name"], "description": s["description"]}
        if params.get("properties"):
            kwargs["parameters"] = params
        decls.append(types.FunctionDeclaration(**kwargs))
    return [types.Tool(function_declarations=decls)]


def run(db: Session, user: User, message: str, attached_file_ids: list[uuid.UUID],
        history: list[dict] | None = None) -> tuple[str, list[dict]]:
    from google.genai import types

    client = _client()
    specs = core.build_specs()
    manifest = core.file_manifest(db, user, attached_file_ids)
    sys = _SYSTEM
    if manifest:
        sys += "\n\nAttached files:\n" + "\n".join(f"- {f['name']} (id={f['id']}, type={f['type']})" for f in manifest)

    config = types.GenerateContentConfig(
        system_instruction=sys,
        tools=_declarations(specs),
        # keep manual control: do NOT let the SDK auto-execute functions
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = [types.Content(role="user", parts=[types.Part(text=message)])]
    steps: list[dict] = []

    for _ in range(_MAX_STEPS):
        try:
            resp = client.models.generate_content(
                model=settings.gemini_model, contents=contents, config=config
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("gemini generate failed")
            return f"The Gemini service failed: {exc}", steps

        fcalls = getattr(resp, "function_calls", None) or []
        if not fcalls:
            return (resp.text or "").strip() or "(no response)", steps

        contents.append(resp.candidates[0].content)  # model turn w/ the function calls
        parts = []
        for fc in fcalls:
            args = dict(fc.args or {})
            result = core.dispatch(fc.name, args, db, user, attached_file_ids)
            steps.append({"tool": fc.name, "args": args, "result": result})
            parts.append(types.Part.from_function_response(name=fc.name, response=result))
        contents.append(types.Content(role="tool", parts=parts))

    return "I couldn't finish that within a few steps — try rephrasing or doing it in parts.", steps
