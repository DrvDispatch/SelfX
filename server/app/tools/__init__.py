"""Tool package. discover() imports every module here so @register-decorated
adapters self-register — new adapter files need NO edits anywhere else."""

import importlib
import logging
import pkgutil

logger = logging.getLogger("selfx.tools")

_discovered = False


def discover() -> None:
    """Import every module in this package exactly once (idempotent)."""
    global _discovered
    if _discovered:
        return
    _discovered = True
    for mod in pkgutil.iter_modules(__path__):
        if mod.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"{__name__}.{mod.name}")
        except Exception:
            # one broken adapter must not take down the whole suite
            logger.exception("failed to import tool module '%s' — skipping it", mod.name)
