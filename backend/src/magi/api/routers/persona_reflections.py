"""Thought inspection and suppression; reads never trigger model work."""

from fastapi import APIRouter, HTTPException, Response

from ...identity.defaults import CANONICAL_LOCAL_USER
from ...personality.persona_journal_service import get_persona_journal_service
from ...personality.reflection_models import ReflectionDetail, ReflectionPage, ReflectionShare

persona_reflections_router = APIRouter()


def _service():
    service = get_persona_journal_service()
    if service is None:
        raise HTTPException(503, "Persona reflection is not ready")
    return service


@persona_reflections_router.post("/reflections/share", response_model=ReflectionShare)
async def share_reflection() -> ReflectionShare:
    return await _service().share(str(CANONICAL_LOCAL_USER))


@persona_reflections_router.get("/reflections/{persona_id}", response_model=ReflectionPage)
async def list_reflections(persona_id: str) -> ReflectionPage:
    try:
        return await _service().page(str(CANONICAL_LOCAL_USER), persona_id)
    except KeyError as exc:
        raise HTTPException(404, "Persona not found") from exc


@persona_reflections_router.get("/reflections/{persona_id}/{thought_id}", response_model=ReflectionDetail)
async def get_reflection(persona_id: str, thought_id: str) -> ReflectionDetail:
    try:
        return await _service().detail(str(CANONICAL_LOCAL_USER), persona_id, thought_id)
    except KeyError as exc:
        raise HTTPException(404, "Thought not found") from exc


@persona_reflections_router.delete("/reflections/{persona_id}/{thought_id}", status_code=204)
async def dismiss_reflection(persona_id: str, thought_id: str) -> Response:
    try:
        await _service().dismiss(str(CANONICAL_LOCAL_USER), persona_id, thought_id)
        return Response(status_code=204)
    except KeyError as exc:
        raise HTTPException(404, "Thought not found") from exc
