"""Transactional personal-item storage shared by UI, tools, and source proposals."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, time as day_time
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import aiosqlite

from ..core.sqlite import SqliteProfile, sqlite_connection_async
from .models import (
    ItemDetail,
    ItemFields,
    ItemPage,
    MutationResult,
    PersonalItem,
    TaskChange,
    TaskConflictError,
    TaskMutation,
    TaskNotFoundError,
    TaskReference,
)

_PROFILE = SqliteProfile(synchronous="FULL")
_CLOSED = {"completed", "cancelled"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _item(row: aiosqlite.Row) -> PersonalItem:
    data = dict(row)
    data["references"] = json.loads(data.pop("references_json"))
    data.pop("defer_epoch", None)
    return PersonalItem.model_validate(data)


def time_epoch(value: str | None, timezone: str) -> float | None:
    """Resolve dates at local midnight and offset timestamps without guessing a zone."""
    if value is None:
        return None
    if len(value) == 10:
        parsed = datetime.combine(
            datetime.fromisoformat(value).date(), day_time(), ZoneInfo(timezone)
        )
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.timestamp()


class PersonalTaskStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def _read(self, db: aiosqlite.Connection, user_id: str, item_id: str) -> PersonalItem:
        cursor = await db.execute(
            "SELECT * FROM personal_items WHERE user_id=? AND id=?", (user_id, item_id)
        )
        row = await cursor.fetchone()
        if row is None:
            raise TaskNotFoundError("Personal item not found")
        return _item(row)

    async def get(self, user_id: str, item_id: str, *, history_offset: int = 0) -> ItemDetail:
        async with sqlite_connection_async(self.db_path, profile=_PROFILE) as db:
            await db.execute("BEGIN")
            item = await self._read(db, user_id, item_id)
            children = await db.execute(
                "SELECT * FROM personal_items WHERE user_id=? AND parent_id=? ORDER BY created_at,id",
                (user_id, item_id),
            )
            history = await db.execute(
                "SELECT * FROM personal_item_changes WHERE user_id=? AND item_id=? ORDER BY id DESC LIMIT 51 OFFSET ?",
                (user_id, item_id, history_offset),
            )
            rows = await history.fetchall()
            changes = [
                TaskChange(
                    id=row["id"],
                    item_id=item_id,
                    action=row["action"],
                    actor=row["actor"],
                    version=row["version"],
                    note=row["note"],
                    changes=json.loads(row["changes_json"]),
                    references=json.loads(row["references_json"]),
                    created_at=row["created_at"],
                )
                for row in rows[:50]
            ]
            return ItemDetail(
                item=item,
                children=[_item(row) for row in await children.fetchall()],
                changes=changes,
                next_history_offset=history_offset + 50 if len(rows) > 50 else None,
            )

    async def query(
        self,
        user_id: str,
        *,
        view: str = "next",
        search: str = "",
        parent_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ItemPage:
        if view not in {
            "all",
            "next",
            "projects",
            "review",
            "inbox",
            "active",
            "waiting",
            "someday",
            "completed",
            "cancelled",
        }:
            raise ValueError("Unknown personal task view")
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        clauses = ["i.user_id=?"]
        params: list[Any] = [user_id]
        if view == "next":
            clauses += [
                "i.status='active'",
                "i.kind='action'",
                "(i.defer_epoch IS NULL OR i.defer_epoch<=?)",
                "(i.parent_id IS NULL OR EXISTS(SELECT 1 FROM personal_items p WHERE p.id=i.parent_id AND p.user_id=i.user_id AND p.status='active'))",
            ]
            params.append(time.time())
        elif view == "projects":
            clauses += ["i.kind='project'", "i.status NOT IN ('completed','cancelled')"]
        elif view == "review":
            clauses += ["i.status NOT IN ('completed','cancelled')"]
        elif view != "all":
            clauses.append("i.status=?")
            params.append(view)
        if parent_id is not None:
            clauses.append("i.parent_id=?")
            params.append(parent_id)
        if search.strip():
            clauses.append(
                "(instr(lower(i.title),lower(?))>0 OR instr(lower(i.body_md),lower(?))>0)"
            )
            params.extend([search.strip(), search.strip()])
        where = " AND ".join(clauses)
        async with sqlite_connection_async(self.db_path, profile=_PROFILE) as db:
            await db.execute("BEGIN")
            count = await db.execute(f"SELECT COUNT(*) FROM personal_items i WHERE {where}", params)
            total = int((await count.fetchone())[0])
            cursor = await db.execute(
                f"SELECT i.* FROM personal_items i WHERE {where} ORDER BY i.updated_at DESC,i.id LIMIT ? OFFSET ?",
                (*params, limit, offset),
            )
            items = [_item(row) for row in await cursor.fetchall()]
            counts = await db.execute(
                "SELECT status,COUNT(*) AS n FROM personal_items WHERE user_id=? GROUP BY status",
                (user_id,),
            )
            return ItemPage(
                items=items,
                total=total,
                next_offset=offset + limit if offset + limit < total else None,
                counts={row["status"]: row["n"] for row in await counts.fetchall()},
            )

    async def mutate(
        self,
        user_id: str,
        command: TaskMutation,
        *,
        actor: str,
        references: list[TaskReference] | None = None,
        origin: str = "user",
        assigned_id: str | None = None,
    ) -> MutationResult:
        """Apply one versioned command and its receipt in the same durable transaction."""
        request_hash = hashlib.sha256(_json(command.model_dump(mode="json")).encode()).hexdigest()
        now = time.time()
        async with sqlite_connection_async(self.db_path, profile=_PROFILE) as db:
            await db.execute("PRAGMA secure_delete=ON")
            await db.execute("BEGIN IMMEDIATE")
            if assigned_id is not None:
                removed = await db.execute(
                    "SELECT 1 FROM personal_item_changes WHERE user_id=? AND item_id=? AND action='delete' LIMIT 1",
                    (user_id, assigned_id),
                )
                if await removed.fetchone():
                    return MutationResult(deleted_ids=[assigned_id], replayed=True)
            previous = await db.execute(
                "SELECT * FROM personal_item_changes WHERE user_id=? AND request_id=?",
                (user_id, command.request_id),
            )
            receipt = await previous.fetchone()
            if receipt is not None:
                if receipt["request_hash"] != request_hash:
                    raise TaskConflictError("Request identifier was reused with different content")
                try:
                    current = await self._read(db, user_id, receipt["item_id"])
                except TaskNotFoundError:
                    deleted_ids = json.loads(receipt["changes_json"]).get(
                        "deleted_ids", [receipt["item_id"]]
                    )
                    return MutationResult(deleted_ids=deleted_ids, replayed=True)
                return MutationResult(item=current, replayed=True)

            old: PersonalItem | None = None
            if command.action == "create":
                item_id = assigned_id or str(uuid4())
                removed = await db.execute(
                    "SELECT 1 FROM personal_item_changes WHERE user_id=? AND item_id=? AND action='delete' LIMIT 1",
                    (user_id, item_id),
                )
                if await removed.fetchone():
                    return MutationResult(deleted_ids=[item_id], replayed=True)
                data = command.fields.model_dump(exclude_unset=True)
                if origin == "source":
                    data.update(status="inbox", remind_at=None)
                fields = ItemFields.model_validate(data)
                if references:
                    fields.references = _merge_references(fields.references, references)
                version = 1
            else:
                item_id = str(command.item_id)
                old = await self._read(db, user_id, item_id)
                if old.version != command.expected_version:
                    raise TaskConflictError(
                        "Personal item changed; read the latest version before updating"
                    )
                version = old.version + 1
                if command.action == "delete":
                    result = await self._delete(db, user_id, old, command, actor, request_hash, now)
                    await db.commit()
                    await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    return result
                data = {key: getattr(old, key) for key in ItemFields.model_fields}
                patch = command.fields.model_dump(exclude_unset=True)
                data.update(patch)
                if data["status"] in _CLOSED or data["status"] == "someday":
                    data["remind_at"] = None
                fields = ItemFields.model_validate(data)
                if references:
                    fields.references = _merge_references(fields.references, references)

            if fields.status not in {"active", "waiting"}:
                fields.remind_at = None
            if fields.kind == "project" and fields.parent_id:
                raise ValueError("Nested projects are not supported")
            if fields.parent_id:
                parent = await self._read(db, user_id, fields.parent_id)
                if parent.kind != "project" or parent.id == item_id:
                    raise ValueError("An action must belong to a different project")
            if old and old.kind == "project" and fields.kind != "project":
                children = await db.execute(
                    "SELECT 1 FROM personal_items WHERE parent_id=? LIMIT 1", (item_id,)
                )
                if await children.fetchone():
                    raise ValueError("A project with actions cannot become an action")
            if fields.remind_at and (old is None or fields.remind_at != old.remind_at):
                if float(time_epoch(fields.remind_at, fields.timezone) or 0) <= now:
                    raise ValueError("A new reminder must be in the future")
            reminder_changed = old is None or any(
                getattr(old, key) != getattr(fields, key)
                for key in ("remind_at", "status", "parent_id")
            )
            item = PersonalItem(
                **fields.model_dump(),
                id=item_id,
                user_id=user_id,
                origin=old.origin if old else origin,
                version=version,
                created_at=old.created_at if old else now,
                updated_at=now,
                closed_at=(old.closed_at if old and old.status in _CLOSED else now)
                if fields.status in _CLOSED
                else None,
                reminder_revision=(old.reminder_revision if old else 0) + int(reminder_changed),
                reminder_synced_revision=old.reminder_synced_revision if old else 0,
                reminder_delivered_revision=old.reminder_delivered_revision if old else 0,
            )
            values = item.model_dump(mode="json")
            values["references_json"] = _json(values.pop("references"))
            values["defer_epoch"] = time_epoch(item.defer_until, item.timezone)
            columns = list(values)
            await db.execute(
                f"INSERT INTO personal_items ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
                f"ON CONFLICT(id) DO UPDATE SET {','.join(f'{key}=excluded.{key}' for key in columns if key != 'id')}",
                tuple(values.values()),
            )
            changes = {
                key: {"before": getattr(old, key) if old else None, "after": getattr(item, key)}
                for key in ItemFields.model_fields
                if key != "references" and (old is None or getattr(old, key) != getattr(item, key))
            }
            if "body_md" in changes:
                # Keep the context in its single current owner, not copied into every
                # progress response. Hashes identify revisions without a second body.
                changes["body_md"] = {
                    "before_hash": hashlib.sha256(old.body_md.encode()).hexdigest()
                    if old
                    else None,
                    "after_hash": hashlib.sha256(item.body_md.encode()).hexdigest(),
                }
            await self._receipt(
                db,
                user_id,
                item_id,
                command.request_id,
                request_hash,
                command.action,
                actor,
                version,
                command.note,
                changes,
                references or [],
                now,
            )
            await db.commit()
            return MutationResult(item=item)

    async def _receipt(
        self,
        db: aiosqlite.Connection,
        user_id: str,
        item_id: str,
        request_id: str,
        request_hash: str,
        action: str,
        actor: str,
        version: int,
        note: str,
        changes: dict[str, Any],
        references: list[TaskReference],
        now: float,
    ) -> None:
        await db.execute(
            "INSERT INTO personal_item_changes(user_id,item_id,request_id,request_hash,action,actor,version,note,changes_json,references_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                user_id,
                item_id,
                request_id,
                request_hash,
                action,
                actor,
                version,
                note,
                _json(changes),
                _json([ref.model_dump(mode="json") for ref in references]),
                now,
            ),
        )

    async def _delete(
        self,
        db: aiosqlite.Connection,
        user_id: str,
        item: PersonalItem,
        command: TaskMutation,
        actor: str,
        request_hash: str,
        now: float,
    ) -> MutationResult:
        cursor = await db.execute(
            "SELECT id,version FROM personal_items WHERE user_id=? AND parent_id=?",
            (user_id, item.id),
        )
        children = {row["id"]: row["version"] for row in await cursor.fetchall()}
        if children and not command.cascade:
            raise TaskConflictError("Deleting a project with actions requires cascade=true")
        ids = [item.id, *children]
        for item_id in ids:
            # Scrub content but retain content-free receipts so delayed creates and
            # retries cannot recreate data that the user explicitly removed.
            await db.execute(
                "UPDATE personal_item_changes SET note='',changes_json='{}',references_json='[]' WHERE user_id=? AND item_id=?",
                (user_id, item_id),
            )
            await db.execute(
                "DELETE FROM personal_items WHERE user_id=? AND id=?", (user_id, item_id)
            )
            await self._receipt(
                db,
                user_id,
                item_id,
                command.request_id
                if item_id == item.id
                else f"delete:{command.request_id}:{item_id}",
                request_hash,
                "delete",
                actor,
                (item.version if item_id == item.id else children[item_id]) + 1,
                "",
                {"deleted_ids": ids} if item_id == item.id else {},
                [],
                now,
            )
        return MutationResult(deleted_ids=ids)

    async def reminder_items(self) -> list[PersonalItem]:
        async with sqlite_connection_async(self.db_path, profile=_PROFILE) as db:
            rows = await db.execute(
                "SELECT * FROM personal_items WHERE remind_at IS NOT NULL OR reminder_revision!=reminder_synced_revision"
            )
            return [_item(row) for row in await rows.fetchall()]

    async def mark_reminder(self, item: PersonalItem, *, delivered: bool = False) -> None:
        column = "reminder_delivered_revision" if delivered else "reminder_synced_revision"
        async with sqlite_connection_async(self.db_path, profile=_PROFILE) as db:
            await db.execute(
                f"UPDATE personal_items SET {column}=? WHERE id=? AND user_id=? AND reminder_revision=?",
                (item.reminder_revision, item.id, item.user_id, item.reminder_revision),
            )
            await db.commit()

    async def clear_user_content(self) -> int:
        """Erase personal content and keep only content-free anti-resurrection receipts."""
        async with sqlite_connection_async(self.db_path, profile=_PROFILE) as db:
            await db.execute("PRAGMA secure_delete=ON")
            await db.execute("BEGIN IMMEDIATE")
            rows = await db.execute("SELECT id,user_id,version FROM personal_items")
            items = await rows.fetchall()
            await db.execute(
                "UPDATE personal_item_changes SET note='',changes_json='{}',references_json='[]'"
            )
            for row in items:
                await self._receipt(
                    db,
                    row["user_id"],
                    row["id"],
                    f"clear:{uuid4()}",
                    "",
                    "delete",
                    "system",
                    row["version"] + 1,
                    "",
                    {},
                    [],
                    time.time(),
                )
            await db.execute("DELETE FROM personal_items")
            await db.commit()
            await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return len(items)


def _merge_references(left: list[TaskReference], right: list[TaskReference]) -> list[TaskReference]:
    result = {(ref.kind, ref.id): ref for ref in left}
    result.update({(ref.kind, ref.id): ref for ref in right})
    return list(result.values())[-50:]
