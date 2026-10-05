from dataclasses import asdict
import sqlite3

import aiosqlite
import pytest

from magi.memory.l1.chat_sessions import create_chat_session_record, project_chat_event_to_session
from magi.events.events import EventTypes

@pytest.mark.asyncio
@pytest.mark.parametrize("workspace", [None, "/tmp/magi"])
async def test_chat_projection_preserves_persisted_workspace_on_migrated_schema(tmp_path, workspace):
    from magi.db.runner import MIGRATION_TARGETS, run_upgrade_head
    from magi.utils.runtime import RuntimePaths
    paths = RuntimePaths(base_dir=tmp_path / "runtime")
    target = next(target for target in MIGRATION_TARGETS if target.name == "l1")
    run_upgrade_head(paths, targets=(target,))
    path = paths.l1_memory_db_path
    record = create_chat_session_record(user_id="user-1", session_id="session-1", workspace_path=workspace, now=123.0)
    values = asdict(record)
    async with aiosqlite.connect(path) as db:
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        await db.execute(f"INSERT INTO chat_sessions ({columns}) VALUES ({placeholders})", tuple(values.values()))
        await project_chat_event_to_session(db, user_id="user-1", session_id="session-1", event_type=EventTypes.USER_MESSAGE, content="hello", timestamp=124.0)
        await project_chat_event_to_session(db, user_id="user-1", session_id="session-1", event_type=EventTypes.AI_RESPONSE, content="reply", timestamp=125.0)
        await db.commit()
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT workspace_path, message_count, last_message_preview, last_user_message_preview, created_at, updated_at FROM chat_sessions WHERE session_id=?", ("session-1",)).fetchone()
    assert row == (workspace, 2, "reply", "hello", 123.0, 125.0)
