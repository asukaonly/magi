"""GET /api/memory/portrait — persona-rendered observations for chat shell rail."""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ....memory.portrait.contracts import PortraitPayload


logger = logging.getLogger(__name__)


_service_singleton: Any = None
_service_lock = asyncio.Lock()
_service_override: Any = None


async def get_service() -> Any:
    """Resolve the production PortraitService lazily on first request.

    Test code can install a mock via :func:`override_service_for_test`.
    """
    if _service_override is not None:
        return _service_override
    global _service_singleton
    if _service_singleton is None:
        async with _service_lock:
            if _service_singleton is None:
                try:
                    from ....memory.portrait.factory import build_portrait_service
                    from .dependencies import get_chat_read_service
                    _service_singleton = build_portrait_service(
                        chat_read_service_factory=get_chat_read_service,
                    )
                except Exception as exc:
                    logger.warning("portrait service init failed: %s", exc)
                    raise HTTPException(
                        status_code=503,
                        detail="portrait_service_not_initialized",
                    )
    return _service_singleton


@contextmanager
def override_service_for_test(service: Any):
    global _service_override
    _service_override = service
    try:
        yield
    finally:
        _service_override = None


def reset_singleton_for_test() -> None:
    """Clear the lazily-built singleton (test helper)."""
    global _service_singleton
    _service_singleton = None


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/portrait")
    async def get_portrait(
        session_id: str = Query(..., min_length=1),
        user_id: str = Query(..., min_length=1),
        force: bool = Query(False),
        service: Any = Depends(get_service),
    ) -> dict:
        payload: PortraitPayload = await service.get_portrait(
            user_id=user_id,
            session_id=session_id,
            force=force,
        )
        return payload.to_dict()

    return router
