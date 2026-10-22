"""Private attachment authorization metadata for the gateway's native file transport."""

from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..api.runtime_dependencies import require_chat_read_service


class AttachmentLookup(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    user_id: str = Field(min_length=1, max_length=256)
    session_id: str = Field(min_length=1, max_length=128)
    attachment_id: str = Field(min_length=1, max_length=128)


async def resolve_chat_attachment(params: dict[str, Any] | None) -> dict[str, Any]:
    lookup = AttachmentLookup.model_validate(params)
    location = await require_chat_read_service().aget_attachment_location(
        lookup.user_id, lookup.session_id, lookup.attachment_id,
    )
    return {"attachment": asdict(location) if location is not None else None}
