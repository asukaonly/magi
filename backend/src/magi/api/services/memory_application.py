"""Translate memory application failures at the HTTP boundary."""

from collections.abc import Awaitable
from typing import TypeVar
from fastapi import HTTPException
from magi.memory.application_errors import MemoryApplicationError, MemoryFailure

_T = TypeVar("_T")
_STATUS_BY_REASON: dict[MemoryFailure, int] = {
    "invalid_request": 400,
    "not_found": 404,
    "conflict": 409,
    "precondition_required": 428,
    "unavailable": 503,
    "internal": 500,
}


async def memory_application_result(operation: Awaitable[_T]) -> _T:
    """Preserve the public error contract without coupling services to HTTP."""
    try:
        return await operation
    except MemoryApplicationError as exc:
        raise HTTPException(status_code=_STATUS_BY_REASON[exc.reason], detail=exc.detail) from exc
