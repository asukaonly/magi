"""Product destinations and important-event materialization for the inbox."""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .store import NotificationRow, NotificationStore, get_notification_store


class NotificationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["chat", "task", "memory", "extensions"]
    id: str | None = None


def notification_target(row: NotificationRow) -> NotificationTarget | None:
    payload = json.loads(row.payload_json or "{}")
    if row.kind in {"interaction_required", "background_task_finished"}:
        session = payload.get("session_id")
        if isinstance(session, str) and session:
            return NotificationTarget(kind="chat", id=session)
    if row.kind == "personal_task_reminder":
        item = payload.get("personal_item_id")
        if isinstance(item, str) and item:
            return NotificationTarget(kind="task", id=item)
    if payload.get("conflict_type") == "profile_conflict":
        return NotificationTarget(kind="memory")
    if row.kind == "suggestion":
        return NotificationTarget(kind="extensions")
    return None


def materialize_event(
    store: NotificationStore, *, channel: str, user_id: str, session_id: str, payload: dict,
) -> bool:
    if not user_id or not session_id:
        return False
    request = payload.get("request_id")
    if channel in {"control.ask.answered", "control.permission.resolved"} and request:
        row = store.find_active_by_dedup(user_id, "interaction_required", f"{session_id}:{request}")
        if row:
            store.mark_actioned(row.id)
        return row is not None
    if channel in {"control.ask.requested", "control.permission.requested"} and request:
        kind, key = "interaction_required", f"{session_id}:{request}"
        title = "Magi needs your input"
        body = "Open the conversation to review the current request."
    elif channel == "background_task_state_changed" and payload.get("status") in {"succeeded", "failed"}:
        task = payload.get("task_id")
        if not task:
            return False
        kind, key = "background_task_finished", f"{task}:{payload.get('attempt_index', 0)}"
        title = "Task completed" if payload["status"] == "succeeded" else "Task needs attention"
        body = str(payload.get("spec", {}).get("title") or title)
    else:
        return False
    store.insert_once(NotificationRow(
        user_id=user_id, kind=kind, dedupe_key=key, title=title, body=body,
        payload_json=json.dumps({"session_id": session_id}),
    ))
    return True


async def materialize_runtime_event(*, channel: str, user_id: str, session_id: str, payload: dict) -> None:
    from .service import _emit_notification_added_signal
    from ..identity.defaults import CANONICAL_LOCAL_USER

    # Control events may omit an owner; the service has one canonical local owner.
    user_id = user_id or str(CANONICAL_LOCAL_USER)
    store = get_notification_store()
    changed = await asyncio.to_thread(
        materialize_event, store, channel=channel, user_id=user_id, session_id=session_id, payload=payload,
    )
    if changed:
        await _emit_notification_added_signal(
            user_id=user_id, unread_count=await asyncio.to_thread(store.unread_count, user_id),
        )
