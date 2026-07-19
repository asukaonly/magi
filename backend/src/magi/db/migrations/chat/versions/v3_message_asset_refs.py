"""Index canonical chat-message asset ownership."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from alembic import op

revision = "v3"
down_revision = "v2"
branch_labels = None
depends_on = None

_BATCH_SIZE = 500
_SAFE_ASSET_COMPONENT = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _runtime_base_dir(connection: Any) -> Path:
    row = connection.execute("PRAGMA database_list").fetchone()
    db_path = Path(str(row[2] or "")).resolve()
    if db_path.parent.name == "chat" and db_path.parent.parent.name == "data":
        return db_path.parents[2]
    return db_path.parent


def _canonical_asset_reference(
    raw_path: object,
    *,
    base_dir: Path,
    resources_dir: Path,
) -> tuple[str, str] | None:
    normalized = str(raw_path or "").strip()
    if not normalized:
        return None
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    try:
        parent = candidate.parent.resolve()
        parent.relative_to(resources_dir)
        target = parent / candidate.name
        if target.is_symlink():
            return None
        asset_key = target.relative_to(resources_dir).as_posix()
        storage_rel_path = target.relative_to(base_dir).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None
    return asset_key, storage_rel_path


def _safe_component(value: object) -> str | None:
    normalized = str(value or "").strip()
    if not _SAFE_ASSET_COMPONENT.fullmatch(normalized):
        return None
    return normalized


def _exact_attachment_reference(
    raw_path: object,
    *,
    base_dir: Path,
    resources_dir: Path,
    session_id: object,
    turn_id: object,
    attachment_id: object,
) -> tuple[str, str] | None:
    normalized_session_id = _safe_component(session_id)
    normalized_turn_id = _safe_component(turn_id)
    normalized_attachment_id = _safe_component(attachment_id)
    if (
        normalized_session_id is None
        or normalized_turn_id is None
        or normalized_attachment_id is None
    ):
        return None
    reference = _canonical_asset_reference(
        raw_path,
        base_dir=base_dir,
        resources_dir=resources_dir,
    )
    if reference is None:
        return None
    parts = Path(reference[0]).parts
    if (
        len(parts) != 4
        or parts[0] not in {"files", "images"}
        or parts[1] != normalized_session_id
        or parts[2] != normalized_turn_id
        or not parts[3].startswith(f"{normalized_attachment_id}__")
        or parts[3] == f"{normalized_attachment_id}__"
    ):
        return None
    return reference


def _inferred_derived_path(
    *,
    resources_dir: Path,
    session_id: object,
    turn_id: object,
    attachment_id: object,
) -> Path | None:
    normalized_session_id = _safe_component(session_id)
    normalized_turn_id = _safe_component(turn_id)
    normalized_attachment_id = _safe_component(attachment_id)
    if (
        normalized_session_id is None
        or normalized_turn_id is None
        or normalized_attachment_id is None
    ):
        return None
    return (
        resources_dir
        / "derived"
        / normalized_session_id
        / normalized_turn_id
        / f"{normalized_attachment_id}.txt"
    )


def _exact_derived_reference(
    raw_path: object,
    *,
    base_dir: Path,
    resources_dir: Path,
    session_id: object,
    turn_id: object,
    attachment_id: object,
) -> tuple[str, str] | None:
    inferred_path = _inferred_derived_path(
        resources_dir=resources_dir,
        session_id=session_id,
        turn_id=turn_id,
        attachment_id=attachment_id,
    )
    if inferred_path is None:
        return None
    candidate_path = raw_path if str(raw_path or "").strip() else inferred_path
    reference = _canonical_asset_reference(
        candidate_path,
        base_dir=base_dir,
        resources_dir=resources_dir,
    )
    expected = _canonical_asset_reference(
        inferred_path,
        base_dir=base_dir,
        resources_dir=resources_dir,
    )
    if reference is None or expected is None or reference[0] != expected[0]:
        return None
    return reference


def _insert_references(
    connection: Any,
    references: Iterable[tuple[str, str, str, str, int]],
) -> None:
    connection.executemany(
        """
        INSERT OR IGNORE INTO chat_message_asset_refs (
            message_id,
            asset_key,
            storage_rel_path,
            asset_kind,
            created_at_ms
        ) VALUES (?, ?, ?, ?, ?)
        """,
        references,
    )


def _backfill_attachment_rows(
    connection: Any,
    *,
    base_dir: Path,
    resources_dir: Path,
) -> None:
    cursor = connection.execute(
        """
        SELECT message_id, session_id, turn_id, attachment_id,
               storage_rel_path, created_at_ms
        FROM chat_attachments
        ORDER BY message_id, attachment_id
        """
    )
    while rows := cursor.fetchmany(_BATCH_SIZE):
        references: dict[tuple[str, str], tuple[str, str, str, str, int]] = {}
        for row in rows:
            message_id = str(row[0] or "").strip()
            if not message_id:
                continue
            original = _exact_attachment_reference(
                row[4],
                base_dir=base_dir,
                resources_dir=resources_dir,
                session_id=row[1],
                turn_id=row[2],
                attachment_id=row[3],
            )
            if original is not None:
                references[(message_id, original[0])] = (
                    message_id,
                    original[0],
                    original[1],
                    "attachment",
                    int(row[5] or 0),
                )
            inferred = _exact_derived_reference(
                None,
                base_dir=base_dir,
                resources_dir=resources_dir,
                session_id=row[1],
                turn_id=row[2],
                attachment_id=row[3],
            )
            if inferred is not None:
                references[(message_id, inferred[0])] = (
                    message_id,
                    inferred[0],
                    inferred[1],
                    "derived_text",
                    int(row[5] or 0),
                )
        _insert_references(connection, references.values())


def _backfill_payload_rows(
    connection: Any,
    *,
    base_dir: Path,
    resources_dir: Path,
) -> None:
    cursor = connection.execute(
        """
        SELECT message_id, session_id, turn_id, payload_json, created_at_ms
        FROM chat_messages
        WHERE payload_json LIKE '%"attachments"%'
        ORDER BY message_id
        """
    )
    while rows := cursor.fetchmany(_BATCH_SIZE):
        references: dict[tuple[str, str], tuple[str, str, str, str, int]] = {}
        for row in rows:
            message_id = str(row[0] or "").strip()
            if not message_id:
                continue
            try:
                payload = json.loads(str(row[3] or "{}"))
            except (TypeError, ValueError):
                continue
            attachments = payload.get("attachments") if isinstance(payload, dict) else None
            if not isinstance(attachments, list):
                continue
            for attachment in attachments:
                if not isinstance(attachment, dict):
                    continue
                original = _exact_attachment_reference(
                    attachment.get("storage_path"),
                    base_dir=base_dir,
                    resources_dir=resources_dir,
                    session_id=row[1],
                    turn_id=row[2],
                    attachment_id=attachment.get("attachment_id"),
                )
                if original is not None:
                    references[(message_id, original[0])] = (
                        message_id,
                        original[0],
                        original[1],
                        "attachment",
                        int(row[4] or 0),
                    )
                derived = _exact_derived_reference(
                    attachment.get("derived_text_path"),
                    base_dir=base_dir,
                    resources_dir=resources_dir,
                    session_id=row[1],
                    turn_id=row[2],
                    attachment_id=attachment.get("attachment_id"),
                )
                if derived is not None:
                    references[(message_id, derived[0])] = (
                        message_id,
                        derived[0],
                        derived[1],
                        "derived_text",
                        int(row[4] or 0),
                    )
                inferred = _exact_derived_reference(
                    None,
                    base_dir=base_dir,
                    resources_dir=resources_dir,
                    session_id=row[1],
                    turn_id=row[2],
                    attachment_id=attachment.get("attachment_id"),
                )
                if inferred is not None:
                    references[(message_id, inferred[0])] = (
                        message_id,
                        inferred[0],
                        inferred[1],
                        "derived_text",
                        int(row[4] or 0),
                    )
        _insert_references(connection, references.values())


def upgrade() -> None:
    connection: Any = op.get_bind().connection
    base_dir = _runtime_base_dir(connection)
    raw_resources_dir = base_dir / "data" / "resources" / "chat"
    resources_dir = base_dir.resolve() / "data" / "resources" / "chat"
    if raw_resources_dir.resolve() != resources_dir:
        raise RuntimeError("Managed chat resources root was retargeted")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS chat_message_asset_refs (
            message_id TEXT NOT NULL,
            asset_key TEXT NOT NULL,
            storage_rel_path TEXT NOT NULL,
            asset_kind TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            PRIMARY KEY (message_id, asset_key)
        );
        CREATE INDEX IF NOT EXISTS idx_chat_message_asset_refs_asset_key
            ON chat_message_asset_refs(asset_key, message_id);
        """
    )
    _backfill_attachment_rows(
        connection,
        base_dir=base_dir,
        resources_dir=resources_dir,
    )
    _backfill_payload_rows(
        connection,
        base_dir=base_dir,
        resources_dir=resources_dir,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chat_message_asset_refs_asset_key")
    op.execute("DROP TABLE IF EXISTS chat_message_asset_refs")
