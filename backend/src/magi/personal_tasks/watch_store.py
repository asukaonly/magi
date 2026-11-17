"""Watch persistence mixed into the existing personal-task store."""

import hashlib
import json
import time
from uuid import uuid4

from ..core.sqlite import SqliteProfile, secure_compact_sqlite, sqlite_connection_async
from .models import TaskConflictError, TaskNotFoundError
from .watch_models import AttentionWatch, WatchMutation, WatchMutationResult

_PROFILE = SqliteProfile(synchronous="FULL")


def watch_from_row(row: dict) -> AttentionWatch:
    return AttentionWatch(
        **json.loads(row["fields_json"]),
        **{
            key: row[key]
            for key in (
                "id",
                "version",
                "status",
                "created_at",
                "updated_at",
                "last_checked_at",
                "check_status",
            )
        },
        result=json.loads(row["result_json"]) if row["result_json"] else None,
    )


class PersonalWatchStoreMixin:
    db_path: str

    async def watch_rows(self, user_id: str, *, offset: int = 0, limit: int = 51) -> list[dict]:
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM attention_watches WHERE user_id=? ORDER BY updated_at DESC,id LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def watch_row(self, user_id: str, identity: str) -> dict:
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM attention_watches WHERE user_id=? AND id=?", (user_id, identity)
            )
            row = await cursor.fetchone()
            if row is None:
                raise TaskNotFoundError("Attention watch not found")
            return dict(row)

    async def active_watch_rows(self, user_id: str) -> list[dict]:
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM attention_watches WHERE user_id=? AND status='active' ORDER BY COALESCE(last_checked_at,0),id",
                (user_id,),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def mutate_watch(self, user_id: str, command: WatchMutation) -> WatchMutationResult:
        digest = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
        now = time.time()
        async with sqlite_connection_async(self.db_path, profile=_PROFILE) as db:
            await db.execute("PRAGMA secure_delete=ON")
            await db.execute("BEGIN IMMEDIATE")
            receipt = await (
                await db.execute(
                    "SELECT * FROM attention_watch_receipts WHERE user_id=? AND request_id=?",
                    (user_id, command.request_id),
                )
            ).fetchone()
            if receipt:
                if receipt["request_hash"] != digest:
                    raise TaskConflictError("Request ID was used for a different watch change")
                row = await (
                    await db.execute(
                        "SELECT * FROM attention_watches WHERE user_id=? AND id=?",
                        (user_id, receipt["watch_id"]),
                    )
                ).fetchone()
                return WatchMutationResult(
                    watch=watch_from_row(dict(row)) if row else None, replayed=True
                )
            identity = command.watch_id or str(uuid4())
            row = await (
                await db.execute(
                    "SELECT * FROM attention_watches WHERE user_id=? AND id=?", (user_id, identity)
                )
            ).fetchone()
            if command.action != "create":
                if row is None:
                    raise TaskNotFoundError("Attention watch not found")
                if row["version"] != command.expected_version:
                    raise TaskConflictError("Attention watch changed; refresh before editing")
            if command.action == "delete":
                await db.execute("DELETE FROM attention_watches WHERE id=?", (identity,))
            else:
                fields = command.fields or watch_from_row(dict(row))
                status = {
                    "create": "active",
                    "update": "active",
                    "pause": "paused",
                    "resume": "active",
                    "stop": "stopped",
                }[command.action]
                if status == "active":
                    if fields.expires_at and fields.expires_at <= now:
                        raise ValueError("Choose a future expiry before resuming this watch")
                    if fields.item_id:
                        parent = await (
                            await db.execute(
                                "SELECT status FROM personal_items WHERE user_id=? AND id=?",
                                (user_id, fields.item_id),
                            )
                        ).fetchone()
                        if not parent or parent[0] in {"completed", "cancelled"}:
                            raise ValueError("The linked personal item must still be open")
                    count = await (
                        await db.execute(
                            "SELECT COUNT(*) FROM attention_watches WHERE user_id=? AND status='active' AND id!=?",
                            (user_id, identity),
                        )
                    ).fetchone()
                    if count[0] >= 10:
                        raise ValueError(
                            "Pause another watch before adding more than ten active watches"
                        )
                if command.action == "create":
                    await db.execute(
                        "INSERT INTO attention_watches (id,user_id,fields_json,version,status,created_at,updated_at,cursor_time) VALUES (?,?,?,1,?,?,?,?)",
                        (identity, user_id, fields.model_dump_json(), status, now, now, now),
                    )
                elif command.action in {"update", "resume"}:
                    fields_json = (
                        command.fields.model_dump_json() if command.fields else row["fields_json"]
                    )
                    await db.execute(
                        "UPDATE attention_watches SET fields_json=?,version=version+1,status=?,updated_at=?,cursor_time=?,cursor_id='',result_json=NULL,evidence_json='{}',check_status='waiting',last_checked_at=NULL WHERE id=?",
                        (fields_json, status, now, now, identity),
                    )
                else:
                    await db.execute(
                        "UPDATE attention_watches SET version=version+1,status=?,updated_at=? WHERE id=?",
                        (status, now, identity),
                    )
            await db.execute(
                "INSERT INTO attention_watch_receipts VALUES (?,?,?,?)",
                (user_id, command.request_id, digest, identity),
            )
            row = await (
                await db.execute("SELECT * FROM attention_watches WHERE id=?", (identity,))
            ).fetchone()
            await db.commit()
        if command.action in {"delete", "update", "resume"}:
            await secure_compact_sqlite(self.db_path)
        return WatchMutationResult(watch=watch_from_row(dict(row)) if row else None)

    async def reserve_watch_check(self, row: dict) -> bool:
        now = time.time()
        async with sqlite_connection_async(self.db_path, profile=_PROFILE) as db:
            await db.execute("BEGIN IMMEDIATE")
            counts = await (
                await db.execute(
                    "SELECT COUNT(*),SUM(watch_id=?) FROM attention_watch_attempts WHERE user_id=? AND created_at>?",
                    (row["id"], row["user_id"], now - 86400),
                )
            ).fetchone()
            if counts[0] >= 20 or (counts[1] or 0) >= 2:
                return False
            cursor = await db.execute(
                "UPDATE attention_watches SET last_checked_at=?,check_status='checking' WHERE id=? AND version=? AND status='active' AND (last_checked_at IS NULL OR last_checked_at<?)",
                (now, row["id"], row["version"], now - 3600),
            )
            if not cursor.rowcount:
                return False
            await db.execute(
                "DELETE FROM attention_watch_attempts WHERE created_at<?", (now - 86400,)
            )
            await db.execute(
                "INSERT INTO attention_watch_attempts(user_id,watch_id,created_at) VALUES (?,?,?)",
                (row["user_id"], row["id"], now),
            )
            await db.commit()
            return True

    async def finish_watch_check(
        self,
        row: dict,
        *,
        cursor_time: float,
        cursor_id: str,
        result: str | None,
        evidence: dict[str, str],
        governance: str,
        check_status: str,
    ) -> None:
        async with sqlite_connection_async(self.db_path, profile=_PROFILE) as db:
            await db.execute(
                "UPDATE attention_watches SET cursor_time=?,cursor_id=?,result_json=?,evidence_json=?,governance_revision=?,check_status=?,last_checked_at=?,status=CASE WHEN ? IS NOT NULL THEN 'matched' ELSE status END WHERE id=? AND user_id=? AND version=? AND status='active'",
                (
                    cursor_time,
                    cursor_id,
                    result,
                    json.dumps(evidence),
                    governance,
                    check_status,
                    time.time(),
                    result,
                    row["id"],
                    row["user_id"],
                    row["version"],
                ),
            )
            await db.commit()

    async def invalidate_watch_result(self, row: dict) -> None:
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("PRAGMA secure_delete=ON")
            await db.execute(
                "UPDATE attention_watches SET result_json=NULL,evidence_json='{}',check_status='invalidated' WHERE id=? AND version=?",
                (row["id"], row["version"]),
            )
            await db.commit()

    async def forget_watch_events(self, event_ids: list[str]) -> None:
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("PRAGMA secure_delete=ON")
            cursor = await db.execute(
                "UPDATE attention_watches SET result_json=NULL,evidence_json='{}',check_status='invalidated' WHERE EXISTS (SELECT 1 FROM json_each(evidence_json) WHERE key IN (SELECT value FROM json_each(?)))",
                (json.dumps(event_ids),),
            )
            await db.commit()
        if cursor.rowcount:
            await secure_compact_sqlite(self.db_path)

    async def expire_watches(self, user_id: str) -> None:
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                "UPDATE attention_watches SET status=CASE WHEN json_extract(fields_json,'$.expires_at')<=? THEN 'expired' ELSE 'stopped' END,version=version+1 WHERE user_id=? AND status IN ('active','paused') AND (json_extract(fields_json,'$.expires_at')<=? OR (json_extract(fields_json,'$.item_id') IS NOT NULL AND NOT EXISTS (SELECT 1 FROM personal_items WHERE id=json_extract(fields_json,'$.item_id') AND user_id=attention_watches.user_id AND status NOT IN ('completed','cancelled'))))",
                (time.time(), user_id, time.time()),
            )
            await db.commit()
