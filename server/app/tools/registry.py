"""Tool registry: @register decorator, get_tool(), all_tools() (SPEC §6)."""

from .base import Tool

REGISTRY: dict[str, Tool] = {}


def register(cls: type[Tool]) -> type[Tool]:
    """Class decorator: instantiate and add to REGISTRY keyed by slug.

    Raises on missing or duplicate slug so a bad adapter fails fast at import.
    """
    slug = getattr(cls, "slug", "")
    if not slug:
        raise ValueError(f"tool class {cls.__name__} defines no slug")
    if slug in REGISTRY:
        raise ValueError(f"duplicate tool slug '{slug}' ({cls.__name__})")
    REGISTRY[slug] = cls()
    return cls


def get_tool(slug: str) -> Tool | None:
    return REGISTRY.get(slug)


def all_tools() -> list[Tool]:
    return sorted(REGISTRY.values(), key=lambda t: (t.category, t.name))
