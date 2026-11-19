"""Draft a workflow from a bounded catalog using a configured local Ollama model."""

import asyncio
import json

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..config import settings

_STATUS_TIMEOUT = 4.0
_PLAN_TIMEOUT = 35.0
_MAX_PROMPT_CHARS = 500
_MAX_STEPS = 6
_STEP_ID = r"[a-z][a-z0-9_-]{0,31}"
_PLANNER_SLOT = asyncio.Semaphore(1)
_UNAVAILABLE = "The local planner is unavailable. You can choose your workflow settings manually."
_UNSUPPORTED = "The available actions cannot complete this request. Try a shorter instruction or use the tools."

_PLANNER_INSTRUCTION = (
    "Draft a SelfX file workflow for user review. Use at most six steps. Use only actions in the "
    "provided catalog and their documented parameters, types and output roles. The single attached "
    "file is referenced as 'source' and has the source type shown below. Each step gets its own "
    "lowercase id. Its input is 'source' or '<earlier step id>.<output role>'. Use {} for params "
    "when default settings apply. Return a JSON object with supported and steps. Set supported "
    "to false and steps to [] if you cannot satisfy every requested operation using the catalog."
)


class _PlannerStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=rf"^{_STEP_ID}$")
    action: str
    input: str = Field(pattern=rf"^(source|{_STEP_ID}\.{_STEP_ID})$")
    params: dict


class _PlannerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    supported: bool
    steps: list[_PlannerStep] = Field(max_length=_MAX_STEPS)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(_PLAN_TIMEOUT, connect=2.0),
        trust_env=False,
    )


def _tag(name: str) -> str:
    return name if ":" in name.rsplit("/", 1)[-1] else f"{name}:latest"


async def _has_local_model(client: httpx.AsyncClient, model: str) -> bool:
    tag = _tag(model)
    name = tag.lower().rsplit(":", 1)[-1]
    if name == "cloud" or name.endswith("-cloud"):
        return False
    response = await client.get(f"{settings.ollama_url.rstrip('/')}/api/tags")
    response.raise_for_status()
    payload = response.json()
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return False
    for entry in models:
        if not isinstance(entry, dict) or entry.get("remote_model") or entry.get("remote_host"):
            continue
        if any(isinstance(name, str) and _tag(name) == tag for name in (entry.get("name"), entry.get("model"))):
            return True
    return False


async def planner_status() -> dict:
    """Report whether the configured local model is present in Ollama."""
    model = settings.selfx_planner_model.strip()
    if not model:
        return {"available": False, "model": None}
    try:
        async with asyncio.timeout(_STATUS_TIMEOUT), _client() as client:
            available = await _has_local_model(client, model)
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, TimeoutError):
        available = False
    return {"available": available, "model": model}


async def plan_prompt(prompt: str, source_type: str, actions: list[dict]) -> dict:
    """Return a structured draft for the workflow validator."""
    instruction = prompt.strip()
    if not instruction or len(instruction) > _MAX_PROMPT_CHARS:
        raise HTTPException(status_code=422, detail="Enter between 1 and 500 characters.")
    model = settings.selfx_planner_model.strip()
    if not model:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE)
    if not actions:
        raise HTTPException(status_code=422, detail=_UNSUPPORTED)
    if _PLANNER_SLOT.locked():
        raise HTTPException(status_code=503, detail="The local planner is busy. Try again or use manual settings.")

    action_ids = {action["slug"] for action in actions}
    schema = _PlannerDraft.model_json_schema()
    schema["$defs"]["_PlannerStep"]["properties"]["action"]["enum"] = sorted(action_ids)
    catalog = json.dumps({"source_type": source_type, "actions": actions}, ensure_ascii=True, separators=(",", ":"))

    try:
        async with asyncio.timeout(_PLAN_TIMEOUT), _PLANNER_SLOT, _client() as client:
            if not await _has_local_model(client, model):
                raise HTTPException(status_code=503, detail=_UNAVAILABLE)
            response = await client.post(
                f"{settings.ollama_url.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": f"{_PLANNER_INSTRUCTION}\n\nWorkflow catalog\n{catalog}"},
                        {"role": "user", "content": instruction},
                    ],
                    "format": schema,
                    "stream": False,
                    "think": False,
                    "keep_alive": settings.ollama_keep_alive,
                    "options": {"num_ctx": settings.selfx_planner_num_ctx, "num_predict": 1152, "temperature": 0},
                },
            )
            response.raise_for_status()
            result = response.json()
            if (
                not isinstance(result, dict)
                or result.get("remote_model")
                or result.get("remote_host")
                or result.get("done") is not True
                or result.get("done_reason") == "length"
            ):
                raise ValueError("incomplete or remote planner response")
            message = result.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str):
                raise TypeError("invalid planner response")
            draft = _PlannerDraft.model_validate_json(content)
    except (httpx.HTTPError, httpx.InvalidURL, TypeError, ValueError, TimeoutError):
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from None

    if not draft.supported or not draft.steps or any(step.action not in action_ids for step in draft.steps):
        raise HTTPException(status_code=422, detail=_UNSUPPORTED)
    return {"steps": [step.model_dump() for step in draft.steps]}
