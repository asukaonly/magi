"""Persistence for bounded reflection runs and user-suppressed thoughts."""

import hashlib
import json
import time

import aiosqlite

from ..core.sqlite import sqlite_connection_async, secure_compact_sqlite
from .reflection_models import PersonaReflection, ReflectionDraft


class ReflectionStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def forget_events(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM persona_reflections WHERE EXISTS (SELECT 1 FROM json_each(evidence_json) "
                "WHERE key IN (SELECT value FROM json_each(?)))", (json.dumps(event_ids),),
            )
            changed = cursor.rowcount > 0
            await db.commit()
        if changed:
            await secure_compact_sqlite(self.db_path)

    async def rows(self, user_id: str, persona_id: str, *, limit: int = 100) -> list[dict]:
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM persona_reflections WHERE user_id=? AND persona_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, persona_id, limit),
            )
            return [dict(row) for row in await cursor.fetchall()]

    @staticmethod
    def thought(row: dict) -> PersonaReflection:
        return PersonaReflection(
            **json.loads(row["content_json"]), id=row["id"], persona_id=row["persona_id"],
            created_at=row["created_at"], status=row["status"],
        )

    async def reserve(self, user_id: str, persona_id: str, run_key: str, *, daily_limit: int) -> bool:
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT COALESCE(SUM(attempts),0) FROM persona_reflection_runs WHERE user_id=? AND created_at>?",
                (user_id, now - 86400),
            )
            if (await cursor.fetchone())[0] >= daily_limit:
                return False
            cursor = await db.execute("SELECT status, created_at FROM persona_reflection_runs WHERE run_key=?", (run_key,))
            previous = await cursor.fetchone()
            if previous and (previous[0] == "completed" or now - previous[1] < 3600):
                return False
            await db.execute(
                "INSERT INTO persona_reflection_runs (run_key,user_id,persona_id,created_at,status) VALUES (?, ?, ?, ?, 'running') "
                "ON CONFLICT(run_key) DO UPDATE SET created_at=excluded.created_at, status='running', attempts=attempts+1",
                (run_key, user_id, persona_id, now),
            )
            await db.commit()
            return True

    async def finish(self, run_key: str, status: str) -> None:
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("UPDATE persona_reflection_runs SET status=? WHERE run_key=?", (status, run_key))
            await db.commit()

    async def last_run(self, user_id: str, persona_id: str) -> dict | None:
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT created_at, status FROM persona_reflection_runs WHERE user_id=? AND persona_id=? ORDER BY created_at DESC LIMIT 1",
                (user_id, persona_id),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def claim_share(self, user_id: str, persona_id: str, identity: str) -> bool:
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute("SELECT 1 FROM persona_reflections WHERE user_id=? AND shared_at>? LIMIT 1", (user_id, now - 86400))
            if await cursor.fetchone():
                return False
            cursor = await db.execute(
                "UPDATE persona_reflections SET shared_at=? WHERE id=? AND user_id=? AND persona_id=? AND status='active' AND shared_at IS NULL",
                (now, identity, user_id, persona_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def save(self, user_id: str, persona_id: str, *, run_key: str, draft: ReflectionDraft,
                   evidence: dict[str, str], persona_revision: float, governance_revision: str) -> None:
        topic = draft.topic.strip().casefold()
        identity = hashlib.sha256(f"{run_key}:{topic}".encode()).hexdigest()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT 1 FROM persona_reflections WHERE user_id=? AND persona_id=? AND topic=? AND status='dismissed'",
                (user_id, persona_id, topic),
            )
            if await cursor.fetchone():
                return
            await db.execute(
                "UPDATE persona_reflections SET status='stale' WHERE user_id=? AND persona_id=? AND topic=? AND id!=? AND status='active'",
                (user_id, persona_id, topic, identity),
            )
            await db.execute(
                "INSERT OR IGNORE INTO persona_reflections "
                "(id,user_id,persona_id,topic,content_json,evidence_json,persona_revision,governance_revision,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (identity, user_id, persona_id, topic, draft.model_dump_json(), json.dumps(evidence),
                 persona_revision, governance_revision, time.time()),
            )
            await db.commit()

    async def set_status(self, user_id: str, persona_id: str, identity: str, status: str) -> bool:
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE persona_reflections SET status=? WHERE user_id=? AND persona_id=? AND id=? AND status!='dismissed'",
                (status, user_id, persona_id, identity),
            )
            await db.commit()
            return cursor.rowcount > 0
