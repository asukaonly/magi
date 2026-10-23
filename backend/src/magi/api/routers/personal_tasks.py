"""Personal-task API backed by the same command service as Agent tools."""

from fastapi import APIRouter, HTTPException, Query

from ...identity.defaults import CANONICAL_LOCAL_USER
from ...personal_tasks.models import (
    ItemDetail,
    ItemPage,
    MutationResult,
    TaskConflictError,
    TaskMutation,
    TaskNotFoundError,
)
from ...personal_tasks.service import get_personal_task_service

personal_tasks_router = APIRouter()


def _service():
    try:
        return get_personal_task_service()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@personal_tasks_router.get("", response_model=ItemPage)
async def list_personal_tasks(
    view: str = "next",
    search: str = Query(default="", max_length=500),
    parent_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ItemPage:
    try:
        return await _service().store.query(
            str(CANONICAL_LOCAL_USER),
            view=view,
            search=search,
            parent_id=parent_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@personal_tasks_router.get("/{item_id}", response_model=ItemDetail)
async def get_personal_task(
    item_id: str, history_offset: int = Query(default=0, ge=0)
) -> ItemDetail:
    try:
        return await _service().store.get(
            str(CANONICAL_LOCAL_USER), item_id, history_offset=history_offset
        )
    except TaskNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@personal_tasks_router.post("/mutations", response_model=MutationResult)
async def mutate_personal_task(command: TaskMutation) -> MutationResult:
    try:
        return await _service().mutate(str(CANONICAL_LOCAL_USER), command, actor="user")
    except TaskConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except TaskNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
