"""Explicit attention requests use the same owner through UI and chat tools."""

from fastapi import APIRouter, HTTPException, Query

from ...identity.defaults import CANONICAL_LOCAL_USER
from ...personal_tasks.models import TaskConflictError, TaskNotFoundError
from ...personal_tasks.watch_models import (
    AttentionWatch,
    WatchMutation,
    WatchMutationResult,
    WatchPage,
)
from ...personal_tasks.watch_service import get_attention_watch_service

attention_watches_router = APIRouter()


@attention_watches_router.get("/watches", response_model=WatchPage)
async def list_watches(offset: int = Query(default=0, ge=0)) -> WatchPage:
    try:
        return await get_attention_watch_service().page(str(CANONICAL_LOCAL_USER), offset)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@attention_watches_router.get("/watches/{watch_id}", response_model=AttentionWatch)
async def get_watch(watch_id: str) -> AttentionWatch:
    try:
        return await get_attention_watch_service().get(str(CANONICAL_LOCAL_USER), watch_id)
    except TaskNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@attention_watches_router.post("/watch-mutations", response_model=WatchMutationResult)
async def mutate_watch(command: WatchMutation) -> WatchMutationResult:
    try:
        return await get_attention_watch_service().mutate(str(CANONICAL_LOCAL_USER), command)
    except TaskConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except TaskNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
