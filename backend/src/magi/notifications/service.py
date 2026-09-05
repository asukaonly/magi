"""NotificationService: materialize suggestions into durable notifications with
dedup, and expose feed/state transitions for the API. Dismissals are written to
the single source of truth (preferences.suggestion_dismissals) via an injected
``record_dismissal`` callable so the bell and chat share one suppression gate."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, Iterable

from magi.notifications.store import NotificationRow, NotificationStore, get_notification_store

_KIND_SUGGESTION = "suggestion"


def _now_ms() -> int:
    return int(time.time() * 1000)


class NotificationService:
    def __init__(self, *, store: NotificationStore,
                 record_dismissal: "Callable[..., None] | None" = None) -> None:
        self._store = store
        self._record_dismissal = record_dismissal

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
                    "plugins": [
                        item.model_dump() if hasattr(item, "model_dump") else dict(item)
                        for item in (getattr(p, "plugins", []) or [])
                    ],
                },
                ensure_ascii=False,
            )
            self._materialize_one(user_id, dedupe_key, title, body, payload)

    def _materialize_one(self, user_id: str, dedupe_key: str, title: str, body: str, payload_json: str) -> None:
        active = self._store.find_active_by_dedup(user_id, _KIND_SUGGESTION, dedupe_key)
        if active is not None:
            self._store.bump(active.id, body=body, created_at_ms=_now_ms())
            return
        self._store.insert(
            NotificationRow(
                user_id=user_id, kind=_KIND_SUGGESTION, dedupe_key=dedupe_key,
                title=title, body=body, payload_json=payload_json,
                status="unread", created_at_ms=_now_ms(),
            )
        )

    # ---- feed / state (thin pass-throughs the routes call) ----
    def list(
        self,
        user_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        profile_conflicts_only: bool = False,
        before_id: int | None = None,
        exclude_profile_conflicts: bool = False,
    ) -> dict:
        items = self._store.list_for_user(
            user_id,
            limit=None,
            profile_conflicts_only=profile_conflicts_only,
            before_id=before_id,
            exclude_profile_conflicts=exclude_profile_conflicts,
        )
        return {
            "items": items[offset:offset + limit],
            "total": len(items),
            "unread_count": self._store.unread_count(
                user_id,
                exclude_profile_conflicts=exclude_profile_conflicts,
            ),
        }

    def mark_read(self, ids: list[int]) -> None:
        self._store.mark_read(ids)

    def mark_read_all(self, user_id: str) -> None:
        self._store.mark_read_all(user_id)

    def dismiss(self, notification_id: int, kind: str = "explicit") -> None:
        row = self._store.get(notification_id)
        self._store.mark_dismissed(notification_id, kind)
        if row is not None and self._record_dismissal is not None:
            # Persist the localized text the user saw so the restore list shows
            # the same string (not a humanized English dedupe_key).
            self._record_dismissal(row.dedupe_key, kind, row.title)

    def dismiss_all(self, user_id: str, kind: str = "explicit") -> int:
        # Snapshot rows (with their localized titles) BEFORE dismissing so each
        # recorded dismissal carries the title the user saw.
        rows = self._store.list_for_user(user_id)
        seen: set[str] = set()
        count = self._store.mark_dismissed_all(user_id, kind)
        if self._record_dismissal is not None:
            for r in rows:
                if r.dedupe_key in seen:
                    continue
                seen.add(r.dedupe_key)
                self._record_dismissal(r.dedupe_key, kind, r.title)
        return count

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
