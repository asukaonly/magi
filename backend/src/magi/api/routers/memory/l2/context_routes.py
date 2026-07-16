"""Product-facing options for stable memory context scopes."""

from __future__ import annotations

from fastapi import HTTPException, status

from .....memory.context_scope import ContextCatalog
from ..dependencies import _resolve_unified_memory, get_chat_read_service
from ..helpers import canonical_self_id, memory_t
from ..router import memory_router
from ..schemas import MemoryContextOptionsResponse


@memory_router.get(
    "/l2/context-options",
    response_model=MemoryContextOptionsResponse,
)
async def get_memory_context_options() -> MemoryContextOptionsResponse:
    """Return only active workspace-bound projects selectable by users."""
    unified_memory = _resolve_unified_memory()
    l2 = getattr(unified_memory, "l2", None) if unified_memory is not None else None
    if l2 is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t(
                "memory.errors.l2_store_uninitialized",
                "L2 store not initialized",
            ),
        )

    catalog = ContextCatalog(l2.db_path)
    chat_user_id = canonical_self_id(unified_memory).removeprefix("user:")
    workspace_paths = await get_chat_read_service().alist_workspace_paths(chat_user_id)
    options = await catalog.sync_workspace_project_options(
        [str(path).strip() for path in workspace_paths if str(path).strip()]
    )

    return MemoryContextOptionsResponse.model_validate(
        {"items": [option.to_dict() for option in options]}
    )


__all__ = ["get_memory_context_options"]
