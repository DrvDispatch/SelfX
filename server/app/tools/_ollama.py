"""Shared Ollama client for the AI tools (underscore => not a tool module)."""

import re

import httpx

from ..config import settings
from .base import ToolError

# qwen3 and other reasoning models can emit a <think>...</think> block into the
# content even with think:false on older Ollama builds — strip it defensively so
# raw chain-of-thought never lands in a summary/answer/notes file.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _num_ctx() -> int:
    """Context window to request. Defaults to the shared 8192 if config lacks it."""
    return int(getattr(settings, "ollama_num_ctx", 8192))


def _strip_think(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


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
            json={
                "model": model,
                "prompt": text,
                "keep_alive": settings.ollama_keep_alive,
                "options": {"num_ctx": _num_ctx()},
                "think": False,
            },
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0),
        )
    except httpx.HTTPError:
        raise ToolError("could not reach the local AI service (Ollama)") from None
    if r.status_code != 200:
        raise ToolError(f"the embedding model '{model}' is not installed or errored")
    try:
        vec = r.json()["embedding"]
    except (KeyError, ValueError, TypeError):
        raise ToolError("unexpected embedding response from Ollama") from None
    if not vec:
        raise ToolError("the embedding model returned an empty vector")
    return vec


def embed_batch(texts: list[str], model: str) -> list[list[float]]:
    """Embed many texts in ONE POST to /api/embed, preserving input order.

    Falls back to sequential embed() calls (also order-preserving) when the batch
    endpoint is unavailable or returns an unexpected shape, so callers always get
    exactly one vector per input.
    """
    if not texts:
        return []
    try:
        r = httpx.post(
            f"{settings.ollama_url}/api/embed",
            json={
                "model": model,
                "input": list(texts),
                "keep_alive": settings.ollama_keep_alive,
                "options": {"num_ctx": _num_ctx()},
                "think": False,
            },
            timeout=httpx.Timeout(connect=5.0, read=300.0, write=60.0, pool=5.0),
        )
        r.raise_for_status()
        embeddings = r.json()["embeddings"]
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise ValueError("mismatched embeddings length")
        if any(not v for v in embeddings):
            raise ValueError("empty embedding in batch response")
    except Exception:
        # Batch path unavailable/errored — fall back to per-text embed(), order kept.
        return [embed(t, model) for t in texts]
    return embeddings


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
                "options": {"num_ctx": _num_ctx()},
                "think": False,
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
        raw = r.json()["message"]["content"]
    except (KeyError, ValueError, TypeError):
        raise ToolError("the local AI service returned an unexpected response") from None
    content = _strip_think(raw or "")
    if not content:
        raise ToolError(
            "the local AI service returned an empty response — the model may still be "
            "loading; try again in a moment"
        )
    return content
