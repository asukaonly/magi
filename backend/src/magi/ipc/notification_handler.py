"""Private bounded notification feed for the gateway event transport."""
from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..api.runtime_dependencies import get_api_runtime_dependencies


class NotificationCursor(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    after_id: int | None = Field(default=None, ge=0)


async def read_notifications(params: dict[str, Any] | None) -> dict[str, Any]:
    cursor = NotificationCursor.model_validate(params or {})
    store = get_api_runtime_dependencies().runtime_trace_store
    if store is None:
        raise RuntimeError("Notification feed owner is unavailable")
    return asdict(await store.read_notification_feed(after_id=cursor.after_id))


async def read_push_notifications(params: dict[str, Any] | None) -> dict[str, Any]:
    import asyncio
    from ..identity.defaults import CANONICAL_LOCAL_USER
    from ..notifications.store import get_notification_store

    cursor = NotificationCursor.model_validate(params or {})
    return await asyncio.to_thread(get_notification_store().push_feed, str(CANONICAL_LOCAL_USER), cursor.after_id)
