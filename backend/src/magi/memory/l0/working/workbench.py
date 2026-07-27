"""Session-attention helpers for L0 working memory."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import math
import re
import time
import uuid
from typing import Any, Iterable, Mapping, Protocol, cast

import aiosqlite

from ..attention import (
    AttentionActionType,
    AttentionEvidenceMode,
    AttentionKind,
    AttentionStatus,
    AttentionUpdateAction,
)
from ..contracts import L0PromptWorkbenchProjection
from ....core.sqlite import sqlite_connection_async
from .source_forgetting import (
    attention_item_predates_entity_forget,
    attention_item_predates_turn_forget,
    attention_source_references,
    filter_attention_items_by_governance,
    forgotten_attention_entity_cutoffs,
    forgotten_attention_source_references,
    forgotten_attention_turn_cutoffs,
    latest_attention_entity_forget_cutoff,
)
from .serialization import row_to_attention_item

MAX_ATTENTION_ITEMS_PER_SESSION = 24
_TERMINAL_RETENTION_SECONDS = 3600
_DEFAULT_TTL_BY_KIND = {
    AttentionKind.FOCUS: 24 * 3600,
    AttentionKind.SITUATION: 6 * 3600,
    AttentionKind.OPEN_LOOP: 72 * 3600,
    AttentionKind.ACTIVE_OBJECT: 24 * 3600,
    AttentionKind.CONSTRAINT: 24 * 3600,
    AttentionKind.CONSENSUS: 24 * 3600,
}
_RELEVANCE_STOP_WORDS = {
    "and",
    "are",
    "but",
    "for",
    "from",
    "have",
    "that",
    "the",
    "their",
    "them",
    "then",
    "this",
    "user",
    "was",
    "were",
    "what",
    "when",
    "with",
    "you",
    "your",
}


class _L0WorkbenchHostProtocol(Protocol):
    _sessions: dict[str, dict[str, Any]]
    _attention_items: dict[str, dict[str, dict[str, Any]]]
    _checkpoint_lock: asyncio.Lock
    checkpoint_db_path: str

    async def start_session(self, *, session_id: str, **kwargs: Any) -> dict[str, Any]: ...

    async def _start_session_locked(
        self,
        host: Any,
        *,
        session_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def initialize(self) -> None: ...

    async def expire_idle_sessions(self) -> list[str]: ...

    def _schedule_checkpoint(self, session_id: str) -> None: ...


class L0WorkbenchMixin:
    """Own the derived attention frame exposed to prompts and inspection."""

    async def get_attention_snapshot(self, session_id: str) -> dict[str, Any]:
        """Return all live attention items and the current frame revision."""

        host = cast(_L0WorkbenchHostProtocol, self)
        await host.initialize()
        await self._expire_attention_items(session_id)
        async with host._checkpoint_lock:
            session = host._sessions.get(session_id)
            metadata = dict((session or {}).get("metadata") or {})
            items = list(host._attention_items.get(session_id, {}).values())
            items = await self._governed_attention_items(items)
            async with sqlite_connection_async(host.checkpoint_db_path) as db:
                forget_cutoff_at = await latest_attention_entity_forget_cutoff(
                    db
                )
            return {
                "revision": int(metadata.get("attention_revision") or 0),
                "forget_cutoff_at": forget_cutoff_at,
                "last_processed_turn_id": (
                    str(metadata.get("last_processed_turn_id") or "").strip() or None
                ),
                "items": [
                    dict(item)
                    for item in sorted(items, key=_attention_sort_key)
                ],
            }

    async def apply_attention_actions(
        self,
        *,
        session_id: str,
        user_id: str | None = None,
        actions: Iterable[AttentionUpdateAction],
        expected_revision: int,
        last_processed_turn_id: str,
        source_texts: Iterable[str] = (),
        source_turn_accepted_at: Mapping[str, float] | None = None,
    ) -> dict[str, Any] | None:
        """Apply one post-turn attention patch if its base revision is current."""

        host = cast(_L0WorkbenchHostProtocol, self)
        await host.initialize()
        now = time.time()
        normalized_sources = {
            _normalize_text(text)
            for text in source_texts
            if _normalize_text(text)
        }
        normalized_actions = tuple(actions)
        accepted_at_by_turn = _normalize_turn_timestamps(
            source_turn_accepted_at or {}
        )

        async with host._checkpoint_lock:
            session = await host._start_session_locked(
                host,
                session_id=session_id,
                user_id=(str(user_id or "").strip() or None),
            )
            metadata = dict(session.get("metadata") or {})
            current_revision = int(metadata.get("attention_revision") or 0)
            if current_revision != int(expected_revision):
                return None

            items = host._attention_items.setdefault(session_id, {})
            forbidden_refs = await self._forbidden_attention_references(
                normalized_actions,
                items=items,
            )
            turn_cutoffs = await self._attention_turn_cutoffs(
                normalized_actions,
                items=items,
            )
            entity_cutoffs = await self._attention_entity_cutoffs(
                actions=normalized_actions,
                items=items,
            )
            applied = 0
            for action in normalized_actions:
                if attention_source_references(action) & forbidden_refs:
                    continue
                if _attention_action_predates_turn_forget(
                    action,
                    items=items,
                    turn_cutoffs=turn_cutoffs,
                    accepted_at_by_turn=accepted_at_by_turn,
                ):
                    continue
                if _attention_action_predates_entity_forget(
                    action,
                    items=items,
                    entity_cutoffs=entity_cutoffs,
                    accepted_at_by_turn=accepted_at_by_turn,
                ):
                    continue
                applied += self._apply_attention_action(
                    items=items,
                    action=action,
                    now=now,
                    source_texts=normalized_sources,
                    accepted_at_by_turn=accepted_at_by_turn,
                )

            self._remove_expired_and_bound_attention(items, now=now)
            metadata["attention_revision"] = current_revision + 1
            metadata["last_processed_turn_id"] = str(last_processed_turn_id)
            metadata["last_attention_update_at"] = now
            metadata["last_attention_action_count"] = applied
            session["metadata"] = metadata
            session["last_active_at"] = now
            host._schedule_checkpoint(session_id)
            return {
                "revision": current_revision + 1,
                "last_processed_turn_id": str(last_processed_turn_id),
                "items": [
                    dict(item)
                    for item in sorted(items.values(), key=_attention_sort_key)
                ],
            }

    def _apply_attention_action(
        self,
        *,
        items: dict[str, dict[str, Any]],
        action: AttentionUpdateAction,
        now: float,
        source_texts: set[str],
        accepted_at_by_turn: dict[str, float],
    ) -> int:
        target = items.get(str(action.target_item_id or ""))
        if action.action is AttentionActionType.ADD:
            return int(
                self._create_attention_item(
                    items=items,
                    action=action,
                    now=now,
                    source_texts=source_texts,
                    accepted_at_by_turn=accepted_at_by_turn,
                )
            )
        if target is None:
            return 0
        if action.action is AttentionActionType.REINFORCE:
            summary = _safe_summary(action.summary, source_texts)
            if summary:
                target["summary"] = summary
            target["status"] = AttentionStatus.ACTIVE.value
            target["salience"] = max(
                float(target.get("salience") or 0.0),
                float(action.salience),
            )
            target["confidence"] = max(
                float(target.get("confidence") or 0.0),
                float(action.confidence),
            )
            target["last_reinforced_at"] = now
            target["expires_at"] = self._attention_expiry(
                AttentionKind(str(target["kind"])),
                now,
            )
            _merge_attention_sources(
                target,
                action,
                accepted_at_by_turn=accepted_at_by_turn,
            )
            return 1
        if action.action is AttentionActionType.BACKGROUND:
            target["status"] = AttentionStatus.BACKGROUND.value
            target["salience"] = min(float(target.get("salience") or 0.5), 0.4)
            target["last_reinforced_at"] = now
            _merge_attention_sources(
                target,
                action,
                accepted_at_by_turn=accepted_at_by_turn,
            )
            return 1
        if action.action is AttentionActionType.RESOLVE:
            target["status"] = AttentionStatus.RESOLVED.value
            target["last_reinforced_at"] = now
            target["expires_at"] = now + _TERMINAL_RETENTION_SECONDS
            _merge_attention_sources(
                target,
                action,
                accepted_at_by_turn=accepted_at_by_turn,
            )
            return 1
        if action.action is AttentionActionType.SUPERSEDE:
            target["status"] = AttentionStatus.SUPERSEDED.value
            target["last_reinforced_at"] = now
            target["expires_at"] = now + _TERMINAL_RETENTION_SECONDS
            _merge_attention_sources(
                target,
                action,
                accepted_at_by_turn=accepted_at_by_turn,
            )
            created = self._create_attention_item(
                items=items,
                action=action,
                now=now,
                source_texts=source_texts,
                accepted_at_by_turn=accepted_at_by_turn,
                supersedes_item_id=str(target["item_id"]),
            )
            return 1 + int(created)
        return 0

    def _create_attention_item(
        self,
        *,
        items: dict[str, dict[str, Any]],
        action: AttentionUpdateAction,
        now: float,
        source_texts: set[str],
        accepted_at_by_turn: dict[str, float],
        supersedes_item_id: str | None = None,
    ) -> bool:
        if action.kind is None:
            return False
        summary = _safe_summary(action.summary, source_texts)
        if not summary:
            return False
        confidence = float(action.confidence)
        if action.evidence_mode is AttentionEvidenceMode.INFERRED:
            confidence = min(confidence, 0.75)
        item_id = f"attention_{uuid.uuid4().hex}"
        items[item_id] = {
            "item_id": item_id,
            "kind": action.kind.value,
            "summary": summary,
            "status": AttentionStatus.ACTIVE.value,
            "salience": float(action.salience),
            "confidence": confidence,
            "evidence_mode": action.evidence_mode.value,
            "source_turn_ids": list(action.source_turn_ids),
            "source_event_ids": list(action.source_event_ids),
            "entity_id": action.entity_id,
            "task_id": action.task_id,
            "task_attempt": action.task_attempt,
            "first_seen_at": now,
            "last_reinforced_at": now,
            "expires_at": self._attention_expiry(action.kind, now),
            "supersedes_item_id": supersedes_item_id,
            "metadata": {
                "source_turn_accepted_at": _source_turn_timestamp_subset(
                    action.source_turn_ids,
                    accepted_at_by_turn=accepted_at_by_turn,
                )
            },
        }
        return True

    @staticmethod
    def _attention_expiry(kind: AttentionKind, now: float) -> float:
        return now + _DEFAULT_TTL_BY_KIND[kind]

    async def _forbidden_attention_references(
        self,
        actions: tuple[AttentionUpdateAction, ...],
        *,
        items: dict[str, dict[str, Any]],
    ) -> set[str]:
        host = cast(_L0WorkbenchHostProtocol, self)
        references = {
            reference
            for action in actions
            for reference in (
                *action.source_turn_ids,
                *action.source_event_ids,
                *(
                    (items.get(str(action.target_item_id or "")) or {}).get(
                        "source_turn_ids",
                        (),
                    )
                ),
                *(
                    (items.get(str(action.target_item_id or "")) or {}).get(
                        "source_event_ids",
                        (),
                    )
                ),
            )
        }
        if not references:
            return set()
        async with sqlite_connection_async(host.checkpoint_db_path) as db:
            return await forgotten_attention_source_references(db, references)

    async def _attention_turn_cutoffs(
        self,
        actions: tuple[AttentionUpdateAction, ...],
        *,
        items: dict[str, dict[str, Any]],
    ) -> dict[str, float]:
        host = cast(_L0WorkbenchHostProtocol, self)
        turn_ids = {
            turn_id
            for action in actions
            for turn_id in (
                *action.source_turn_ids,
                *(
                    (items.get(str(action.target_item_id or "")) or {}).get(
                        "source_turn_ids",
                        (),
                    )
                ),
            )
        }
        if not turn_ids:
            return {}
        async with sqlite_connection_async(host.checkpoint_db_path) as db:
            return await forgotten_attention_turn_cutoffs(db, turn_ids)

    async def _attention_entity_cutoffs(
        self,
        *,
        actions: tuple[AttentionUpdateAction, ...],
        items: dict[str, dict[str, Any]],
    ) -> dict[str, float]:
        host = cast(_L0WorkbenchHostProtocol, self)
        entity_ids = {
            entity_id
            for action in actions
            for entity_id in _attention_action_entity_ids(
                action,
                items=items,
            )
        }
        if not entity_ids:
            return {}
        async with sqlite_connection_async(host.checkpoint_db_path) as db:
            return await forgotten_attention_entity_cutoffs(db, entity_ids)

    async def _governed_attention_items(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        host = cast(_L0WorkbenchHostProtocol, self)
        try:
            async with sqlite_connection_async(host.checkpoint_db_path) as db:
                return await filter_attention_items_by_governance(db, items)
        except Exception:
            return [
                item
                for item in items
                if not attention_source_references(item)
            ]

    @staticmethod
    def _remove_expired_and_bound_attention(
        items: dict[str, dict[str, Any]],
        *,
        now: float,
    ) -> None:
        for item_id, item in list(items.items()):
            expires_at = item.get("expires_at")
            if expires_at is not None and float(expires_at) <= now:
                items.pop(item_id, None)
        while len(items) > MAX_ATTENTION_ITEMS_PER_SESSION:
            evicted_id = min(
                items,
                key=lambda item_id: (
                    _status_rank(str(items[item_id].get("status") or "")),
                    float(items[item_id].get("salience") or 0.0),
                    float(items[item_id].get("last_reinforced_at") or 0.0),
                ),
            )
            items.pop(evicted_id, None)

    async def get_workbench(self, session_id: str) -> dict[str, Any]:
        """Return the public L0 attention workbench for one session."""

        host = cast(_L0WorkbenchHostProtocol, self)
        await host.initialize()
        await self._expire_attention_items(session_id)
        async with host._checkpoint_lock:
            session = host._sessions.get(session_id)
            items = await self._governed_attention_items(
                list(host._attention_items.get(session_id, {}).values())
            )
            return {
                "session": dict(session) if session else None,
                "attention_items": [
                    dict(item)
                    for item in sorted(items, key=_attention_sort_key)
                ],
            }

    async def get_session_index_snapshot(self) -> dict[str, Any]:
        """Return a stable public snapshot for L0 list and search surfaces."""

        host = cast(_L0WorkbenchHostProtocol, self)
        await host.initialize()
        await self.expire_idle_sessions()
        async with host._checkpoint_lock:
            governed_items = await self._governed_attention_items(
                [
                    item
                    for session_items in host._attention_items.values()
                    for item in session_items.values()
                ]
            )
            governed_ids = {
                str(item.get("item_id") or "")
                for item in governed_items
            }
            return {
                "sessions": deepcopy(host._sessions),
                "attention_by_session": {
                    session_id: {
                        item_id: deepcopy(item)
                        for item_id, item in session_items.items()
                        if item_id in governed_ids
                    }
                    for session_id, session_items in host._attention_items.items()
                },
            }

    async def forget_entity(
        self,
        entity_id: str,
        *,
        forgotten_at: float | None = None,
        operation_id: str | None = None,
    ) -> int:
        """Remove attention items linked to one canonical entity."""

        normalized_entity_id = str(entity_id or "").strip()
        if not normalized_entity_id:
            raise ValueError("entity_id must not be empty")
        cutoff_at = _finite_timestamp(
            time.time() if forgotten_at is None else forgotten_at,
            field_name="forgotten_at",
        )
        normalized_operation_id = str(operation_id or "").strip() or None
        host = cast(_L0WorkbenchHostProtocol, self)
        await host.initialize()
        async with host._checkpoint_lock:
            session_ids = tuple(host._sessions)
            async with sqlite_connection_async(host.checkpoint_db_path) as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    await db.execute(
                        """
                        INSERT INTO l0_forgotten_attention_entities(
                            entity_id, cutoff_at, operation_id, updated_at
                        ) VALUES (?, ?, ?, ?)
                        ON CONFLICT(entity_id) DO UPDATE SET
                            cutoff_at = MAX(
                                l0_forgotten_attention_entities.cutoff_at,
                                excluded.cutoff_at
                            ),
                            operation_id = CASE
                                WHEN excluded.cutoff_at >=
                                     l0_forgotten_attention_entities.cutoff_at
                                THEN excluded.operation_id
                                ELSE l0_forgotten_attention_entities.operation_id
                            END,
                            updated_at = MAX(
                                l0_forgotten_attention_entities.updated_at,
                                excluded.updated_at
                            )
                        """,
                        (
                            normalized_entity_id,
                            cutoff_at,
                            normalized_operation_id,
                            time.time(),
                        ),
                    )
                    async with db.execute(
                        """
                        SELECT cutoff_at
                        FROM l0_forgotten_attention_entities
                        WHERE entity_id = ?
                        """,
                        (normalized_entity_id,),
                    ) as cursor:
                        row = await cursor.fetchone()
                    effective_cutoff = float(row[0]) if row is not None else cutoff_at
                    live_ids = {
                        item_id
                        for items in host._attention_items.values()
                        for item_id, item in items.items()
                        if str(item.get("entity_id") or "")
                        == normalized_entity_id
                        and attention_item_predates_entity_forget(
                            item,
                            cutoff_at=effective_cutoff,
                        )
                    }
                    db.row_factory = aiosqlite.Row
                    checkpoint_ids: set[str] = set()
                    async with db.execute(
                        """
                        SELECT *
                        FROM l0_attention_items
                        WHERE entity_id = ?
                        """,
                        (normalized_entity_id,),
                    ) as cursor:
                        async for checkpoint_row in cursor:
                            item_id = str(checkpoint_row["item_id"])
                            try:
                                checkpoint_item = row_to_attention_item(
                                    checkpoint_row
                                )
                            except (TypeError, ValueError, KeyError):
                                checkpoint_ids.add(item_id)
                                continue
                            if attention_item_predates_entity_forget(
                                checkpoint_item,
                                cutoff_at=effective_cutoff,
                            ):
                                checkpoint_ids.add(item_id)
                    if checkpoint_ids:
                        await db.executemany(
                            "DELETE FROM l0_attention_items WHERE item_id = ?",
                            [(item_id,) for item_id in sorted(checkpoint_ids)],
                        )
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
            for items in host._attention_items.values():
                for item_id in live_ids:
                    items.pop(item_id, None)
            for session_id in session_ids:
                session = host._sessions.get(session_id)
                if session is None:
                    continue
                metadata = dict(session.get("metadata") or {})
                metadata["attention_revision"] = (
                    int(metadata.get("attention_revision") or 0) + 1
                )
                session["metadata"] = metadata
                host._schedule_checkpoint(session_id)
            return len(live_ids | checkpoint_ids)

    async def get_prompt_workbench_projection(
        self,
        session_id: str,
        *,
        query: str = "",
    ) -> L0PromptWorkbenchProjection:
        """Return active attention plus query-relevant background context."""

        workbench = await self.get_workbench(session_id)
        prompt_items: list[dict[str, Any]] = []
        for item in workbench.get("attention_items", []):
            status = str(item.get("status") or "")
            confidence_floor = (
                0.7
                if str(item.get("evidence_mode") or "")
                == AttentionEvidenceMode.INFERRED.value
                else 0.5
            )
            if float(item.get("confidence") or 0.0) < confidence_floor:
                continue
            if status == AttentionStatus.ACTIVE.value:
                if float(item.get("salience") or 0.0) >= 0.35:
                    prompt_items.append(item)
                continue
            if (
                status == AttentionStatus.BACKGROUND.value
                and float(item.get("salience") or 0.0) >= 0.15
                and _attention_matches_query(item, query)
            ):
                prompt_items.append(item)
        return L0PromptWorkbenchProjection(
            session=workbench.get("session"),
            attention_items=prompt_items[:12],
        )

    async def _expire_attention_items(self, session_id: str) -> None:
        host = cast(_L0WorkbenchHostProtocol, self)
        now = time.time()
        async with host._checkpoint_lock:
            items = host._attention_items.get(session_id, {})
            before = len(items)
            self._remove_expired_and_bound_attention(items, now=now)
            if len(items) != before:
                host._schedule_checkpoint(session_id)


def _safe_summary(summary: str | None, source_texts: set[str]) -> str | None:
    normalized = _normalize_text(summary)
    if not normalized:
        return None
    if normalized in source_texts:
        return None
    return " ".join(str(summary or "").split())[:240]


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


def _normalize_turn_timestamps(
    values: Mapping[str, float],
) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for raw_turn_id, raw_timestamp in values.items():
        turn_id = str(raw_turn_id or "").strip()
        if not turn_id:
            continue
        try:
            timestamp = float(raw_timestamp)
        except (TypeError, ValueError):
            continue
        if math.isfinite(timestamp) and timestamp > 0:
            normalized[turn_id] = timestamp
    return normalized


def _attention_action_entity_ids(
    action: AttentionUpdateAction,
    *,
    items: dict[str, dict[str, Any]],
) -> set[str]:
    entity_ids: set[str] = set()
    direct = str(action.entity_id or "").strip()
    if direct:
        entity_ids.add(direct)
    target = items.get(str(action.target_item_id or ""))
    target_entity = str((target or {}).get("entity_id") or "").strip()
    if target_entity:
        entity_ids.add(target_entity)
    return entity_ids


def _attention_action_predates_turn_forget(
    action: AttentionUpdateAction,
    *,
    items: dict[str, dict[str, Any]],
    turn_cutoffs: dict[str, float],
    accepted_at_by_turn: dict[str, float],
) -> bool:
    """Return whether any action source was accepted before its delete cutoff."""

    for turn_id in action.source_turn_ids:
        cutoff_at = turn_cutoffs.get(turn_id)
        if cutoff_at is None:
            continue
        accepted_at = accepted_at_by_turn.get(turn_id)
        if accepted_at is None or accepted_at <= cutoff_at:
            return True
    target = items.get(str(action.target_item_id or ""))
    return bool(
        target
        and attention_item_predates_turn_forget(
            target,
            turn_cutoffs=turn_cutoffs,
        )
    )


def _attention_action_predates_entity_forget(
    action: AttentionUpdateAction,
    *,
    items: dict[str, dict[str, Any]],
    entity_cutoffs: dict[str, float],
    accepted_at_by_turn: dict[str, float],
) -> bool:
    return any(
        not action.source_turn_ids
        or not all(
            accepted_at_by_turn.get(turn_id, 0.0) > cutoff_at
            for turn_id in action.source_turn_ids
        )
        for entity_id in _attention_action_entity_ids(action, items=items)
        if (cutoff_at := entity_cutoffs.get(entity_id)) is not None
    )


def _finite_timestamp(value: Any, *, field_name: str) -> float:
    try:
        timestamp = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite timestamp") from exc
    if not math.isfinite(timestamp) or timestamp <= 0:
        raise ValueError(f"{field_name} must be a finite timestamp")
    return timestamp


def _source_turn_timestamp_subset(
    source_turn_ids: Iterable[str],
    *,
    accepted_at_by_turn: dict[str, float],
) -> dict[str, float]:
    return {
        turn_id: accepted_at_by_turn[turn_id]
        for turn_id in source_turn_ids
        if turn_id in accepted_at_by_turn
    }


def _attention_matches_query(item: dict[str, Any], query: str) -> bool:
    query_terms = _relevance_terms(query)
    if not query_terms:
        return False
    candidate = " ".join(
        [
            str(item.get("summary") or ""),
            str(item.get("entity_id") or ""),
            str(item.get("task_id") or ""),
        ]
    )
    return bool(query_terms & _relevance_terms(candidate))


def _relevance_terms(value: Any) -> set[str]:
    normalized = _normalize_text(value)
    terms = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9._:/+-]{2,}", normalized)
        if len(token) >= 3 and token not in _RELEVANCE_STOP_WORDS
    }
    for segment in re.findall(r"[\u3400-\u9fff]{2,}", normalized):
        terms.update(
            segment[index : index + 2]
            for index in range(len(segment) - 1)
        )
    return terms


def _merge_attention_sources(
    item: dict[str, Any],
    action: AttentionUpdateAction,
    *,
    accepted_at_by_turn: dict[str, float],
) -> None:
    if action.task_id:
        item["task_id"] = action.task_id
    if action.task_attempt is not None:
        item["task_attempt"] = int(action.task_attempt)
    item["source_turn_ids"] = list(
        dict.fromkeys(
            [
                *item.get("source_turn_ids", []),
                *action.source_turn_ids,
            ]
        )
    )[-8:]
    item["source_event_ids"] = list(
        dict.fromkeys(
            [
                *item.get("source_event_ids", []),
                *action.source_event_ids,
            ]
        )
    )[-8:]
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    raw_timestamps = metadata.get("source_turn_accepted_at")
    timestamps = dict(raw_timestamps) if isinstance(raw_timestamps, dict) else {}
    timestamps.update(
        _source_turn_timestamp_subset(
            action.source_turn_ids,
            accepted_at_by_turn=accepted_at_by_turn,
        )
    )
    retained_turn_ids = set(item["source_turn_ids"])
    metadata["source_turn_accepted_at"] = {
        turn_id: timestamp
        for turn_id, timestamp in timestamps.items()
        if turn_id in retained_turn_ids
    }
    item["metadata"] = metadata


def _attention_sort_key(item: dict[str, Any]) -> tuple[int, float, float]:
    return (
        -_status_rank(str(item.get("status") or "")),
        -float(item.get("salience") or 0.0),
        -float(item.get("last_reinforced_at") or 0.0),
    )


def _status_rank(status: str) -> int:
    return {
        AttentionStatus.ACTIVE.value: 3,
        AttentionStatus.BACKGROUND.value: 2,
        AttentionStatus.RESOLVED.value: 1,
        AttentionStatus.SUPERSEDED.value: 0,
    }.get(status, 0)


__all__ = [
    "L0WorkbenchMixin",
    "MAX_ATTENTION_ITEMS_PER_SESSION",
]
