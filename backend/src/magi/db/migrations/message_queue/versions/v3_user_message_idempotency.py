"""Add durable user-message command idempotency tombstones."""

from __future__ import annotations

import hashlib
import json

from alembic import op

revision = "v3"
down_revision = "v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_user_message_idempotency (
            correlation_id TEXT PRIMARY KEY,
            payload_fingerprint TEXT NOT NULL,
            first_command_id INTEGER NOT NULL,
            delivery_status TEXT NOT NULL DEFAULT 'open',
            created_at REAL NOT NULL
        )
        """
    )
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        DELETE FROM runtime_commands
        WHERE command_type = 'user_message'
          AND status IN ('pending', 'claimed')
          AND (
              EXISTS (
                  SELECT 1
                  FROM runtime_commands AS completed
                  WHERE completed.command_type = 'user_message'
                    AND completed.correlation_id = runtime_commands.correlation_id
                    AND completed.status = 'completed'
              )
              OR EXISTS (
                  SELECT 1
                  FROM runtime_commands AS earlier
                  WHERE earlier.command_type = 'user_message'
                    AND earlier.correlation_id = runtime_commands.correlation_id
                    AND earlier.status IN ('pending', 'claimed')
                    AND earlier.command_id < runtime_commands.command_id
              )
          )
        """
    )
    rows = connection.exec_driver_sql(
        """
        SELECT correlation_id, payload_json, command_id, created_at, status
        FROM runtime_commands
        WHERE command_type = 'user_message'
        ORDER BY correlation_id ASC,
                 CASE
                     WHEN status = 'completed' THEN 0
                     WHEN status IN ('pending', 'claimed') THEN 1
                     ELSE 2
                 END ASC,
                 command_id ASC
        """
    ).fetchall()
    receipt_columns = {
        str(row[1])
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(runtime_user_message_idempotency)"
        ).fetchall()
    }
    for correlation_id, payload_json, command_id, created_at, _status in rows:
        values = (
            str(correlation_id),
            _payload_fingerprint(str(payload_json)),
            int(command_id),
            _receipt_status(str(_status)),
            float(created_at),
        )
        if "current_command_id" in receipt_columns:
            connection.exec_driver_sql(
                """
                INSERT OR IGNORE INTO runtime_user_message_idempotency (
                    correlation_id, payload_fingerprint, current_attempt_no,
                    current_command_id, delivery_status, created_at
                ) VALUES (?, ?, 0, ?, ?, ?)
                """,
                values,
            )
        else:
            connection.exec_driver_sql(
                """
                INSERT OR IGNORE INTO runtime_user_message_idempotency (
                    correlation_id, payload_fingerprint, first_command_id,
                    delivery_status, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                values,
            )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS runtime_user_message_idempotency")


def _payload_fingerprint(payload_json: str) -> str:
    try:
        payload = json.loads(payload_json)
        if isinstance(payload, dict):
            payload.pop("delivery_attempt_no", None)
            payload.pop("runtime_command_id", None)
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        canonical = payload_json
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _receipt_status(command_status: str) -> str:
    if command_status == "completed":
        return "completed"
    if command_status == "failed":
        return "failed"
    return "open"
