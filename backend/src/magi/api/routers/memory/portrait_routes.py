"""GET /api/memory/portrait — persona-rendered observations for chat shell rail."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ....core.runtime_bindings import require_chat_portrait_service


logger = logging.getLogger(__name__)


_service_override: Any = None


async def get_service() -> Any:
    """Resolve the runtime-bound chat portrait service.

    Test code can install a mock via :func:`override_service_for_test`.
    """
    if _service_override is not None:
        return _service_override
    try:
        return require_chat_portrait_service()
    except RuntimeError as exc:
        logger.warning("portrait service binding unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="portrait_service_not_initialized",
        ) from exc


@contextmanager
def override_service_for_test(service: Any):
    global _service_override
    _service_override = service
    try:
        yield
    finally:
        _service_override = None


def reset_singleton_for_test() -> None:
    """Retained for existing tests; the route now uses runtime bindings."""


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/portrait")
    async def get_portrait(
        session_id: str = Query(..., min_length=1),
        user_id: str = Query(..., min_length=1),
        force: bool = Query(False),
        service: Any = Depends(get_service),
    ) -> dict:
        payload = await service.get_portrait(
            user_id=user_id,
            session_id=session_id,
            force=force,
        )
        return payload.to_dict()

    return router
