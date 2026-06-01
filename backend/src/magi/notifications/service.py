"""NotificationService: materialize suggestions into durable notifications with
dedup + cooldown, and expose feed/state transitions for the API."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Iterable

from magi.notifications.store import NotificationRow, NotificationStore, get_notification_store

# Cooldown windows by dismiss kind (mirrors suggestion-dismissal TTLs).
_COOLDOWN_MS = {
    "transient": 7 * 86_400_000,
    "explicit": 30 * 86_400_000,
    "never": None,  # never re-create
}
_KIND_SUGGESTION = "suggestion"


def _now_ms() -> int:
    return int(time.time() * 1000)


class NotificationService:
    def __init__(self, *, store: NotificationStore) -> None:
        self._store = store

    # ---- materialization ----
    def materialize(self, *, user_id: str, locale: str, proposals: Iterable[Any]) -> None:
        loc = "zh" if str(locale).startswith("zh") else "en"
        for p in proposals:
            dedupe_key = getattr(p, "dedupe_key", None) or getattr(p, "category")
            rationale = getattr(p, "rationale", {}) or {}
            body = rationale.get(loc) or rationale.get("en") or ""
            title = body  # v1: title == localized rationale (short, single line)
            payload = json.dumps(
                {
                    "category": getattr(p, "category", dedupe_key),
                    "plugin_ids": list(getattr(p, "plugin_ids", []) or []),
                    "installable_plugin_ids": list(getattr(p, "installable_plugin_ids", []) or []),
                },
                ensure_ascii=False,
            )
            self._materialize_one(user_id, dedupe_key, title, body, payload)

    def _materialize_one(self, user_id: str, dedupe_key: str, title: str, body: str, payload_json: str) -> None:
        active = self._store.find_active_by_dedup(user_id, _KIND_SUGGESTION, dedupe_key)
        if active is not None:
            self._store.bump(active.id, body=body, created_at_ms=_now_ms())
            return
        latest = self._store.find_latest_by_dedup(user_id, _KIND_SUGGESTION, dedupe_key)
        if latest is not None and not self._cooldown_elapsed(latest):
            return  # suppressed within cooldown
        self._store.insert(
            NotificationRow(
                user_id=user_id, kind=_KIND_SUGGESTION, dedupe_key=dedupe_key,
                title=title, body=body, payload_json=payload_json,
                status="unread", created_at_ms=_now_ms(),
            )
        )

    def _cooldown_elapsed(self, latest: NotificationRow) -> bool:
        if latest.status == "dismissed":
            window = _COOLDOWN_MS.get(latest.dismiss_kind or "explicit", _COOLDOWN_MS["explicit"])
            if window is None:  # "never"
                return False
            ref = latest.dismissed_at_ms or 0
            return _now_ms() - ref >= window
        # actioned: re-suggest only after the explicit window (user already connected it once)
        if latest.status == "actioned":
            ref = latest.actioned_at_ms or 0
            return _now_ms() - ref >= _COOLDOWN_MS["explicit"]
        return True

    # ---- feed / state (thin pass-throughs the routes call) ----
    def list(self, user_id: str, *, limit: int = 50, before_id: int | None = None) -> dict:
        items = self._store.list_for_user(user_id, limit=limit, before_id=before_id)
        return {"items": items, "unread_count": self._store.unread_count(user_id)}

    def mark_read(self, ids: list[int]) -> None:
        self._store.mark_read(ids)

    def mark_read_all(self, user_id: str) -> None:
        self._store.mark_read_all(user_id)

    def dismiss(self, notification_id: int, kind: str = "explicit") -> None:
        self._store.mark_dismissed(notification_id, kind)

    def dismiss_all(self, user_id: str, kind: str = "explicit") -> int:
        return self._store.mark_dismissed_all(user_id, kind)

    def action(self, notification_id: int) -> None:
        self._store.mark_actioned(notification_id)


async def materialize_suggestion_notifications(*, user_id: str, locale: str, proposals) -> None:
    """Materialize proposals into durable notifications, then emit a live
    'user_notification_added' signal so the frontend refreshes. Best-effort:
    callers wrap in try/except so /check never fails."""
    store = get_notification_store()
    svc = NotificationService(store=store)
    # store methods are sync sqlite3 → run off the event loop
    await asyncio.to_thread(svc.materialize, user_id=user_id, locale=locale, proposals=list(proposals))
    unread = await asyncio.to_thread(store.unread_count, user_id)
    await _emit_notification_added_signal(user_id=user_id, unread_count=unread)


async def _emit_notification_added_signal(*, user_id: str, unread_count: int) -> None:
    import json as _json
    from magi.runtime_trace.provider import resolve_runtime_trace_store
    from magi.runtime_trace.contracts import RuntimeNotificationRecord
    rec = RuntimeNotificationRecord(
        notification_id=0,
        channel="user_notification_added",
        payload_json=_json.dumps({"unread_count": unread_count}, ensure_ascii=False),
        created_at_ms=0,  # required field; store coalesces 0 -> int(time.time()*1000)
        user_id=user_id,
        session_id="",
    )
    # resolve_runtime_trace_store().append_notification is async (aiosqlite)
    await resolve_runtime_trace_store().append_notification(rec)
