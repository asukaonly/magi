"""Control-owned question persistence and atomic answer arbitration."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Protocol

from ..core.sqlite import sqlite_connection_async
from .ask_contracts import AskState


class AskRepository(Protocol):
    async def open(self, *, session_id: str, ask: AskState) -> None: ...
    async def recover(self, *, now: float) -> list[tuple[str, AskState]]: ...
    async def resolve(self, *, request_id: str, answer: str, now: float) -> AskState | None: ...
    async def close(self, *, request_id: str, answer: str | None, resolution: str, now: float) -> AskState | None: ...
    async def clear(self, *, session_id: str | None = None) -> None: ...


def _encode(ask: AskState) -> str:
    return json.dumps(asdict(ask), ensure_ascii=False, allow_nan=False)


def _decode(value: str) -> AskState:
    fields = json.loads(value)
    fields["options"] = tuple(fields["options"])
    return AskState(**fields)


class SqliteAskRepository:
    """Own row conversion and compare-and-set semantics for the SQLite adapter."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def open(self, *, session_id: str, ask: AskState) -> None:
        async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            prior = await db.execute_fetchall("SELECT request_id,state_json FROM control_asks WHERE session_id=? AND resolution IS NULL", (session_id,))
            for request_id, value in prior:
                previous = _decode(value)
                previous.resolution, previous.answered_at = "cancelled", ask.asked_at
                await db.execute("UPDATE control_asks SET resolution='cancelled',state_json=? WHERE request_id=?", (_encode(previous), request_id))
            await db.execute("INSERT INTO control_asks(request_id,session_id,asked_at,resolution,state_json) VALUES (?,?,?,NULL,?)", (ask.request_id, session_id, ask.asked_at, _encode(ask)))
            await db.commit()

    async def recover(self, *, now: float) -> list[tuple[str, AskState]]:
        # A question is meaningful only while its execution continuation exists.
        # Coroutines cannot survive a worker restart; never resurrect permissions.
        async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            rows = await db.execute_fetchall("SELECT session_id,request_id,state_json FROM control_asks ORDER BY asked_at")
            latest: dict[str, AskState] = {}
            for session_id, request_id, value in rows:
                ask = _decode(value)
                if ask.status == "pending":
                    ask.resolution = "timeout" if ask.expires_at is not None and ask.expires_at <= now else "cancelled"
                    ask.answered_at = now
                    await db.execute("UPDATE control_asks SET resolution=?,state_json=? WHERE request_id=?", (ask.resolution, _encode(ask), request_id))
                latest[session_id] = ask
            await db.commit()
            return list(latest.items())

    async def resolve(self, *, request_id: str, answer: str, now: float) -> AskState | None:
        return await self.close(request_id=request_id, answer=answer, resolution="user", now=now)

    async def close(self, *, request_id: str, answer: str | None, resolution: str, now: float) -> AskState | None:
        if resolution not in {"user", "timeout", "cancelled"}:
            raise ValueError("Invalid question resolution")
        async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            rows = await db.execute_fetchall("SELECT state_json FROM control_asks WHERE request_id=? AND resolution IS NULL", (request_id,))
            if not rows:
                return None
            ask = _decode(rows[0][0])
            if resolution == "user" and (
                not isinstance(answer, str) or not answer.strip()
                or (ask.expires_at is not None and ask.expires_at <= now)
                or (not ask.allow_free_text and answer.strip() not in ask.options)
            ):
                return None
            ask.answer = answer.strip() if resolution == "user" else None
            ask.resolution, ask.answered_at = resolution, now
            changed = await db.execute("UPDATE control_asks SET resolution=?,state_json=? WHERE request_id=? AND resolution IS NULL", (resolution, _encode(ask), request_id))
            await db.commit()
            return ask if changed.rowcount == 1 else None

    async def clear(self, *, session_id: str | None = None) -> None:
        async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
            await db.execute("DELETE FROM control_asks WHERE (? IS NULL OR session_id=?)", (session_id, session_id))
            await db.commit()
