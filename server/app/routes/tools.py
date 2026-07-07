"""GET /tools — list every registered tool with availability (SPEC §5)."""

import logging

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..models import User
from ..schemas import ToolInfo
from ..tools.registry import all_tools

logger = logging.getLogger("selfx.routes.tools")

router = APIRouter(tags=["tools"])


@router.get("/tools", response_model=list[ToolInfo])
def list_tools(user: User = Depends(get_current_user)) -> list[ToolInfo]:
    result: list[ToolInfo] = []
    for tool in all_tools():
        try:
            available, reason = tool.available()
        except Exception:
            logger.exception("availability check failed for tool '%s'", tool.slug)
            available, reason = False, "availability check failed"
        result.append(
            ToolInfo(
                slug=tool.slug,
                name=tool.name,
                category=tool.category,
                description=tool.description,
                accepts=list(tool.accepts),
                multi_file=tool.multi_file,
                min_files=tool.min_files,
                params_schema=tool.params_schema,
                queue=tool.queue,
                available=available,
                unavailable_reason=None if available else (reason or "unavailable"),
            )
        )
    return result
