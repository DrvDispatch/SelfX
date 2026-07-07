"""Shared Ollama client for the AI tools (underscore => not a tool module)."""

import httpx

from ..config import settings
from .base import ToolError


def is_available() -> tuple[bool, str | None]:
    """Ping Ollama's /api/tags so tools can report availability without a full call."""
    try:
        r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=2.0)
        if r.status_code == 200:
            return True, None
    except Exception:
        pass
    return False, "the local AI service (Ollama) is not running — start the 'ai' profile"


def has_model(prefix: str) -> bool:
    try:
        r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=2.0)
        if r.status_code == 200:
            return any(m.get("name", "").startswith(prefix) for m in r.json().get("models", []))
    except Exception:
        pass
    return False


def embed(text: str, model: str) -> list[float]:
    """Return an embedding vector for `text` from Ollama's /api/embeddings."""
    try:
        r = httpx.post(
            f"{settings.ollama_url}/api/embeddings",
            json={"model": model, "prompt": text, "keep_alive": settings.ollama_keep_alive},
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0),
        )
    except httpx.HTTPError:
        raise ToolError("could not reach the local AI service (Ollama)") from None
    if r.status_code != 200:
        raise ToolError(f"the embedding model '{model}' is not installed or errored")
    try:
        return r.json()["embedding"]
    except (KeyError, ValueError, TypeError):
        raise ToolError("unexpected embedding response from Ollama") from None


def chat(messages: list[dict]) -> str:
    """Call Ollama /api/chat (non-streaming) and return the assistant message content."""
    try:
        r = httpx.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": False,
                "keep_alive": settings.ollama_keep_alive,
            },
            timeout=httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=5.0),
        )
    except httpx.HTTPError:
        raise ToolError("could not reach the local AI service (Ollama)") from None
    if r.status_code == 404:
        raise ToolError(
            f"the AI model '{settings.ollama_model}' is not installed — "
            f"run: docker compose exec ollama ollama pull {settings.ollama_model}"
        )
    if r.status_code != 200:
        raise ToolError("the local AI service returned an error")
    try:
        return r.json()["message"]["content"].strip()
    except (KeyError, ValueError, TypeError):
        raise ToolError("the local AI service returned an unexpected response") from None
