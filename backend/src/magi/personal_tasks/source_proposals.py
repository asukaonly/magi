"""Validate plugin-provided candidates while preserving host source identity."""

from pydantic import BaseModel, ConfigDict, Field, field_validator
import json
import hashlib

from ..identity.defaults import CANONICAL_LOCAL_USER
from .models import TaskReference
from .service import get_personal_task_service


class SourceTaskProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    body_md: str = Field(default="", max_length=100_000)

    @field_validator("key", "title")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Source proposal keys and titles must not be blank")
        return value.strip()


async def ingest_source_task_proposals(
    proposals: list[dict],
    *,
    connection_id: str,
    source_id: str,
    object_id: str,
    event_id: str,
) -> None:
    """Admit explicit plugin candidates to inbox only, never to active commitments."""
    if len(proposals) > 20:
        raise ValueError("A source item may contribute at most twenty personal-task proposals")
    parsed = [SourceTaskProposal.model_validate(proposal) for proposal in proposals]
    if len({proposal.key for proposal in parsed}) != len(parsed):
        raise ValueError("Source task proposal keys must be unique within an object")
    service = get_personal_task_service()
    for proposal in parsed:
        identity = json.dumps(
            [connection_id, source_id, object_id, proposal.key], ensure_ascii=False
        )
        await service.propose(
            user_id=str(CANONICAL_LOCAL_USER),
            source_key=identity,
            title=proposal.title,
            body_md=proposal.body_md,
            references=[
                TaskReference(kind="memory", id=event_id),
                TaskReference(
                    kind="source",
                    id=hashlib.sha256(identity.encode()).hexdigest(),
                    label=source_id[:300],
                ),
            ],
        )
