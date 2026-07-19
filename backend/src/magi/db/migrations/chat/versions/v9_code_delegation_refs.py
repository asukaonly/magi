"""Track code-delegation artifacts through chat deletion recovery."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from alembic import op

revision = "v9"
down_revision = "v8"
branch_labels = None
depends_on = None

_DELEGATION_ID_PATTERN = re.compile(r"[0-9a-fA-F]{32}")


def _backfill_message_references() -> None:
    connection = op.get_bind()
    rows = connection.exec_driver_sql(
        """
        SELECT
            message.message_id,
            message.session_id,
            reference.value,
            message.created_at_ms
        FROM chat_messages AS message,
             json_each(
                 CASE
                     WHEN json_valid(message.payload_json)
                     THEN message.payload_json
                     ELSE '{}'
                 END,
                 '$.code_agent_delegations'
             ) AS reference
        WHERE json_valid(message.payload_json)
          AND json_type(
              message.payload_json,
              '$.code_agent_delegations'
          ) = 'array'
        """
    ).fetchall()
    for message_id, session_id, raw_reference, created_at_ms in rows:
        try:
            reference: Any = json.loads(str(raw_reference))
        except (TypeError, ValueError):
            continue
        if not isinstance(reference, dict):
            continue
        delegation_id = str(reference.get("delegation_id") or "").strip()
        turn_id = str(reference.get("turn_id") or "").strip()
        workspace_path = str(reference.get("workspace_path") or "").strip()
        if (
            not _DELEGATION_ID_PATTERN.fullmatch(delegation_id)
            or not turn_id
            or not workspace_path
            or not Path(workspace_path).expanduser().is_absolute()
        ):
            continue
        connection.exec_driver_sql(
            """
            INSERT OR IGNORE INTO chat_message_code_delegation_refs(
                message_id,
                session_id,
                delegation_id,
                turn_id,
                workspace_path,
                created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(message_id),
                str(session_id),
                delegation_id.lower(),
                turn_id,
                workspace_path,
                int(created_at_ms),
            ),
        )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_message_code_delegation_refs (
            message_id TEXT NOT NULL,
            session_id TEXT COLLATE NOCASE NOT NULL,
            delegation_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            workspace_path TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            PRIMARY KEY (message_id, delegation_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_message_code_delegation_scope
        ON chat_message_code_delegation_refs(
            workspace_path,
            session_id,
            delegation_id,
            message_id
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_code_delegation_artifacts (
            workspace_path TEXT NOT NULL,
            session_id TEXT COLLATE NOCASE NOT NULL,
            delegation_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            PRIMARY KEY (workspace_path, session_id, delegation_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_code_delegation_artifacts_scope
        ON chat_code_delegation_artifacts(
            session_id,
            turn_id,
            delegation_id
        )
        """
    )
    _backfill_message_references()
    op.execute(
        """
        INSERT OR IGNORE INTO chat_code_delegation_artifacts(
            workspace_path,
            session_id,
            delegation_id,
            turn_id,
            created_at_ms
        )
        SELECT DISTINCT
            workspace_path,
            session_id,
            delegation_id,
            turn_id,
            created_at_ms
        FROM chat_message_code_delegation_refs
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS idx_chat_code_delegation_artifacts_scope"
    )
    op.execute("DROP TABLE IF EXISTS chat_code_delegation_artifacts")
    op.execute(
        "DROP INDEX IF EXISTS idx_chat_message_code_delegation_scope"
    )
    op.execute("DROP TABLE IF EXISTS chat_message_code_delegation_refs")
