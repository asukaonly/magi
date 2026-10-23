"""Session lifecycle operations for the chat read service."""

from __future__ import annotations

from ...cleanup_plan import ChatCleanupPlan
from ..retired_turns import retire_turns

from ..statements import statement, mysql_ascii_lower

from ..relational import ChatRow, ChatReadConnection, ChatReadDatabase

from ....core.chat_errors import ChatSessionCreationConflict, ChatSessionNotFound

import json
import re
import uuid
from typing import Protocol, cast

from ....core.code_agent_artifacts import (
    WorkspaceSessionArtifactReference,
)
from ....core.logger import get_logger
from ....memory.l1.chat_sessions import ChatSessionRecord, create_chat_session_record
from ...workspace_identity import claim_workspace_identity
from .asset_ownership import (
    assert_unambiguous_session_asset_scope,
    unshared_asset_references,
)
from .deletion_phases import (
    DELETION_TURN_IDS_TABLE,
    delete_code_delegation_artifact_records,
    delete_all_model_context,
    delete_session_model_context,
    delete_scoped_asset_references,
    delete_scoped_code_delegation_references,
    delete_scoped_message_tombstones,
    redact_scoped_messages,
    replace_deletion_scope,
)
from .code_delegation_ownership import (
    unshared_code_delegation_references,
)
from magi.core.chat_read_models import (
    ChatMessageSourceIdentity,
    ChatSessionRenameResult,
    ChatSessionSummary,
    SessionWorkspaceUpdateResult,
)
from .schema import (
    CHAT_ASSISTANT_MEMORY_OUTBOX_TABLE,
    CHAT_ATTACHMENTS_TABLE,
    CHAT_CODE_DELEGATION_ARTIFACTS_TABLE,
    CHAT_CLEARED_SESSION_SCOPES_TABLE,
    CHAT_CLEARED_MESSAGE_SCOPES_TABLE,
    CHAT_CONTEXT_SUMMARIES_TABLE,
    CHAT_CONTEXT_USAGE_SNAPSHOTS_TABLE,
    CHAT_GLOBAL_CLEAR_INTENT_TABLE,
    CHAT_MESSAGE_ASSET_REFS_TABLE,
    CHAT_MESSAGE_CODE_DELEGATION_REFS_TABLE,
    CHAT_MESSAGES_TABLE,
    CHAT_MODEL_CONTEXT_BOUNDARIES_TABLE,
    CHAT_MODEL_CONTEXT_EPOCHS_TABLE,
    CHAT_MODEL_CONTEXT_EVENTS_TABLE,
    CHAT_MODEL_CONTEXT_HEADS_TABLE,
    CHAT_MODEL_CONTEXT_REVISIONS_TABLE,
    CHAT_MODEL_CONTEXT_RUN_HEADS_TABLE,
    CHAT_MODEL_CONTEXT_SURFACE_NODES_TABLE,
    CHAT_RUN_CONSUMED_EVENTS_TABLE,
    CHAT_SESSION_CREATION_REQUESTS_TABLE,
    CHAT_SESSIONS_TABLE,
    CHAT_TURNS_TABLE,
    CHAT_USER_TURN_DELIVERY_TABLE,
    CHAT_WORKSPACE_SESSION_CLEANUP_TABLE,
)

logger = get_logger(__name__)
_SESSION_CREATION_IDEMPOTENCY_KEY_PATTERN = re.compile(
    r"^[A-Za-z0-9_-]{1,128}$"
)


def _rhythm_segment_index(payload_json: object) -> int | None:
    try:
        payload = json.loads(str(payload_json or "{}"))
        rhythm = payload.get("rhythm")
        segment_index = rhythm.get("segment_index") if isinstance(rhythm, dict) else None
    except (AttributeError, TypeError, ValueError):
        return None
    if (
        not isinstance(segment_index, int)
        or isinstance(segment_index, bool)
        or segment_index < 0
    ):
        return None
    return segment_index


def _source_message_id_from_row(
    row: ChatRow,
    *,
    rhythm_message_ids: dict[tuple[str, int], str],
) -> str:
    message_id = str(row["message_id"])
    if str(row["message_kind"] or "") != "assistant_rhythm_segment":
        return message_id
    turn_id = str(row["turn_id"] or "").strip()
    segment_index = _rhythm_segment_index(row["payload_json"])
    if not turn_id or segment_index is None:
        return message_id
    canonical_sequence_no = int(row["sequence_no"] or 0) - segment_index
    return rhythm_message_ids.get(
        (turn_id, canonical_sequence_no),
        message_id,
    )


def _background_task_id_from_payload(payload_json: object) -> str | None:
    try:
        payload = json.loads(str(payload_json or "{}"))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return str(payload.get("background_task_id") or "").strip() or None


def _message_source_identity_from_row(
    row: ChatRow,
    *,
    rhythm_message_ids: dict[tuple[str, int], str],
) -> ChatMessageSourceIdentity:
    return ChatMessageSourceIdentity(
        message_id=str(row["message_id"]),
        session_id=str(row["session_id"]),
        user_id=str(row["user_id"]),
        role=str(row["role"]),
        turn_id=str(row["turn_id"] or "").strip() or None,
        run_id=str(row["run_id"] or "").strip() or None,
        run_revision=int(row["run_revision"] or 0),
        source_message_id=_source_message_id_from_row(
            row,
            rhythm_message_ids=rhythm_message_ids,
        ),
        background_task_id=_background_task_id_from_payload(
            row["payload_json"]
        ),
    )


def _rhythm_message_ids_for_turns(
    conn: ChatReadConnection,
    *,
    user_id: str,
    session_id: str,
    turn_ids: set[str],
) -> dict[tuple[str, int], str]:
    normalized_turn_ids = sorted(
        normalized
        for value in turn_ids
        if (normalized := str(value or "").strip())
    )
    if not normalized_turn_ids:
        return {}
    placeholders = ", ".join("?" for _ in normalized_turn_ids)
    return {
        (
            str(candidate["turn_id"]),
            int(candidate["sequence_no"] or 0),
        ): str(candidate["message_id"])
        for candidate in conn.execute(
            statement("""
            SELECT message_id, turn_id, sequence_no
            FROM {part0}
            WHERE user_id = ? AND session_id = ?
              AND turn_id IN ({part1})
              AND role = 'assistant'
              AND message_kind = 'assistant_rhythm_segment'
            """, part0=CHAT_MESSAGES_TABLE, part1=placeholders),
            (
                user_id,
                session_id,
                *normalized_turn_ids,
            ),
        ).fetchall()
    }


class _ChatSessionOperationsHost(Protocol):
    database: ChatReadDatabase

    def _get_conn(self) -> ChatReadConnection: ...

    def _normalize_workspace_path(self, workspace_path: str | None) -> str | None: ...

    def _row_to_session_summary(self, row: ChatRow) -> ChatSessionSummary: ...





    def _list_chat_snapshot_asset_references(
        self,
        *,
        session_id: str,
        turn_ids: list[str],
        delete_entire_session: bool,
    ) -> list[tuple[str, str]]: ...




def _insert_or_return_session(
    *,
    host: _ChatSessionOperationsHost,
    record: ChatSessionRecord,
    normalized_user_id: str,
    normalized_idempotency_key: str | None,
) -> tuple[str, bool]:
    conn = host._get_conn()
    conn.begin_write()
    try:
        if normalized_idempotency_key is not None:
            existing = conn.execute(
                statement("""
                SELECT
                    request.session_id,
                    session.user_id,
                    session.archived_at_ms,
                    session.deleted_at_ms
                FROM {part0} AS request
                LEFT JOIN {part1} AS session
                  ON session.session_id = request.session_id
                WHERE request.user_id = ?
                  AND request.idempotency_key = ?
                LIMIT 1
                """, part0=CHAT_SESSION_CREATION_REQUESTS_TABLE, part1=CHAT_SESSIONS_TABLE),
                (normalized_user_id, normalized_idempotency_key),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["user_id"] or "") == normalized_user_id
                    and existing["archived_at_ms"] is None
                    and existing["deleted_at_ms"] is None
                ):
                    conn.commit()
                    return str(existing["session_id"]), False
                raise ChatSessionCreationConflict("Idempotency key is not available")

        conn.execute(
            statement("""
            INSERT INTO {part0} (
                session_id, user_id, title, title_overridden, summary, created_at_ms, updated_at_ms,
                last_message_at_ms, last_user_message_at_ms, last_message_preview,
                last_user_message_preview, message_count, workspace_path, archived_at_ms, deleted_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, part0=CHAT_SESSIONS_TABLE),
            (
                record.session_id,
                record.user_id,
                record.title,
                1 if record.title_overridden else 0,
                record.summary,
                int(record.created_at * 1000),
                int(record.updated_at * 1000),
                int(record.last_message_at * 1000) if record.last_message_at is not None else None,
                (
                    int(record.last_user_message_at * 1000)
                    if record.last_user_message_at is not None
                    else None
                ),
                record.last_message_preview,
                record.last_user_message_preview,
                record.message_count,
                record.workspace_path,
                int(record.archived_at * 1000) if record.archived_at is not None else None,
                int(record.deleted_at * 1000) if record.deleted_at is not None else None,
            ),
        )
        if normalized_idempotency_key is not None:
            conn.execute(
                statement("""
                INSERT INTO {part0} (
                    user_id,
                    idempotency_key,
                    session_id,
                    created_at_ms
                ) VALUES (?, ?, ?, ?)
                """, part0=CHAT_SESSION_CREATION_REQUESTS_TABLE),
                (
                    normalized_user_id,
                    normalized_idempotency_key,
                    record.session_id,
                    int(record.created_at * 1000),
                ),
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return str(record.session_id), True


class ChatSessionOperationsMixin:
    """Create, update, list, and delete chat sessions."""

    def list_session_turn_ids(self, user_id: str, session_id: str) -> list[str]:
        """Return every persisted turn identity owned by one chat session."""
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")
        rows = (
            host._get_conn()
            .execute(
                statement("""
            SELECT turn_id
            FROM {part0}
            WHERE user_id = ? AND session_id = ?
            UNION
            SELECT turn_id
            FROM {part1}
            WHERE user_id = ? AND session_id = ?
              AND TRIM(COALESCE(turn_id, '')) != ''
            ORDER BY turn_id
            """, part0=CHAT_TURNS_TABLE, part1=CHAT_MESSAGES_TABLE),
                (
                    normalized_user_id,
                    normalized_session_id,
                    normalized_user_id,
                    normalized_session_id,
                ),
            )
            .fetchall()
        )
        return [str(row[0]) for row in rows if str(row[0] or "").strip()]

    def backfill_cleared_chat_scopes(
        self,
        session_ids: list[str],
        message_scopes: list[tuple[str, str]],
    ) -> dict[str, int]:
        """Restore durable chat barriers from completed forget selectors."""

        host = cast(_ChatSessionOperationsHost, self)
        normalized_session_ids = sorted(
            {
                value
                for raw_value in session_ids
                if (value := str(raw_value or "").strip())
            }
        )
        normalized_message_scopes = sorted(
            {
                (session_id, message_id)
                for raw_session_id, raw_message_id in message_scopes
                if (session_id := str(raw_session_id or "").strip())
                and (message_id := str(raw_message_id or "").strip())
            }
        )
        if not normalized_session_ids and not normalized_message_scopes:
            return {"sessions": 0, "messages": 0}
        conn = host._get_conn()
        conn.begin_write()
        try:
            session_cursor = conn.executemany(
                statement("""
                INSERT OR IGNORE INTO {part0}(
                    session_id,
                    cleared_at_ms
                ) VALUES (
                    ?,
                    CAST(strftime('%s', 'now') AS INTEGER) * 1000
                )
                """, mysql="""
                INSERT IGNORE INTO {part0}(
                    session_id,
                    cleared_at_ms
                ) VALUES (
                    ?,
                    CAST(UNIX_TIMESTAMP() AS SIGNED) * 1000
                )
                """, part0=CHAT_CLEARED_SESSION_SCOPES_TABLE),
                [(session_id,) for session_id in normalized_session_ids],
            )
            message_cursor = conn.executemany(
                statement("""
                INSERT OR IGNORE INTO {part0}(
                    session_id,
                    message_id,
                    cleared_at_ms
                ) VALUES (
                    ?,
                    ?,
                    CAST(strftime('%s', 'now') AS INTEGER) * 1000
                )
                """, mysql="""
                INSERT IGNORE INTO {part0}(
                    session_id,
                    message_id,
                    cleared_at_ms
                ) VALUES (
                    ?,
                    ?,
                    CAST(UNIX_TIMESTAMP() AS SIGNED) * 1000
                )
                """, part0=CHAT_CLEARED_MESSAGE_SCOPES_TABLE),
                normalized_message_scopes,
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return {
            "sessions": max(int(session_cursor.rowcount or 0), 0),
            "messages": max(int(message_cursor.rowcount or 0), 0),
        }

    def get_message_source_identity(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> ChatMessageSourceIdentity | None:
        """Resolve one persisted message to its exact memory source identity."""
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        normalized_message_id = str(message_id or "").strip()
        if not normalized_user_id or not normalized_session_id or not normalized_message_id:
            raise ValueError("User ID, session ID, and message ID are required")
        conn = host._get_conn()
        row = (
            conn
            .execute(
                statement("""
            SELECT messages.message_id, messages.session_id, messages.user_id,
                   messages.role, messages.turn_id, messages.message_kind,
                   messages.payload_json, messages.sequence_no,
                   turns.run_id, turns.run_revision
            FROM {part0} AS messages
            LEFT JOIN {part1} AS turns
              ON turns.turn_id = messages.turn_id
             AND turns.session_id = messages.session_id
             AND turns.user_id = messages.user_id
            WHERE messages.user_id = ?
              AND messages.session_id = ?
              AND messages.message_id = ?
            """, part0=CHAT_MESSAGES_TABLE, part1=CHAT_TURNS_TABLE),
                (normalized_user_id, normalized_session_id, normalized_message_id),
            )
            .fetchone()
        )
        if row is None:
            return None
        turn_id = str(row["turn_id"] or "").strip() or None
        rhythm_message_ids = _rhythm_message_ids_for_turns(
            conn,
            user_id=normalized_user_id,
            session_id=normalized_session_id,
            turn_ids=(
                {turn_id}
                if turn_id
                and str(row["message_kind"] or "")
                == "assistant_rhythm_segment"
                else set()
            ),
        )
        return _message_source_identity_from_row(
            row,
            rhythm_message_ids=rhythm_message_ids,
        )

    def list_message_replacement_source_identities(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> list[ChatMessageSourceIdentity]:
        """Snapshot the complete logical replacement chain for one message."""

        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        normalized_message_id = str(message_id or "").strip()
        if (
            not normalized_user_id
            or not normalized_session_id
            or not normalized_message_id
        ):
            raise ValueError("User ID, session ID, and message ID are required")
        conn = host._get_conn()
        rows = (
            conn.execute(
                f"""
                WITH RECURSIVE replacement_chain(message_id) AS (
                    SELECT message_id
                    FROM {CHAT_MESSAGES_TABLE}
                    WHERE user_id = ? AND session_id = ? AND message_id = ?
                    UNION
                    SELECT candidate.message_id
                    FROM {CHAT_MESSAGES_TABLE} AS candidate
                    JOIN replacement_chain AS chain
                      ON candidate.replaces_message_id = chain.message_id
                    WHERE candidate.user_id = ? AND candidate.session_id = ?
                    UNION
                    SELECT candidate.replaces_message_id
                    FROM {CHAT_MESSAGES_TABLE} AS candidate
                    JOIN replacement_chain AS chain
                      ON candidate.message_id = chain.message_id
                    WHERE candidate.user_id = ? AND candidate.session_id = ?
                      AND candidate.replaces_message_id IS NOT NULL
                )
                SELECT messages.message_id, messages.session_id, messages.user_id,
                       messages.role, messages.turn_id, messages.message_kind,
                       messages.payload_json, messages.sequence_no,
                       messages.created_at_ms, turns.run_id, turns.run_revision
                FROM {CHAT_MESSAGES_TABLE} AS messages
                JOIN replacement_chain AS chain
                  ON chain.message_id = messages.message_id
                LEFT JOIN {CHAT_TURNS_TABLE} AS turns
                  ON turns.turn_id = messages.turn_id
                 AND turns.session_id = messages.session_id
                 AND turns.user_id = messages.user_id
                WHERE messages.user_id = ? AND messages.session_id = ?
                ORDER BY messages.created_at_ms, messages.sequence_no,
                         messages.message_id
                """,
                (
                    normalized_user_id,
                    normalized_session_id,
                    normalized_message_id,
                    normalized_user_id,
                    normalized_session_id,
                    normalized_user_id,
                    normalized_session_id,
                    normalized_user_id,
                    normalized_session_id,
                ),
            )
            .fetchall()
        )
        rhythm_message_ids = _rhythm_message_ids_for_turns(
            conn,
            user_id=normalized_user_id,
            session_id=normalized_session_id,
            turn_ids={
                str(row["turn_id"] or "").strip()
                for row in rows
                if str(row["message_kind"] or "")
                == "assistant_rhythm_segment"
            },
        )
        return [
            _message_source_identity_from_row(
                row,
                rhythm_message_ids=rhythm_message_ids,
            )
            for row in rows
        ]

    def list_session_message_source_identities(
        self,
        user_id: str,
        session_id: str,
    ) -> list[ChatMessageSourceIdentity]:
        """Snapshot every message source before a transcript is cleared."""
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")
        rows = (
            host._get_conn()
            .execute(
                statement("""
                SELECT messages.message_id, messages.session_id, messages.user_id,
                       messages.role, messages.turn_id, messages.message_kind,
                       messages.payload_json, messages.sequence_no,
                       turns.run_id, turns.run_revision
                FROM {part0} AS messages
                LEFT JOIN {part1} AS turns
                  ON turns.turn_id = messages.turn_id
                 AND turns.session_id = messages.session_id
                 AND turns.user_id = messages.user_id
                WHERE messages.user_id = ? AND messages.session_id = ?
                ORDER BY messages.created_at_ms, messages.sequence_no,
                         messages.message_id
                """, part0=CHAT_MESSAGES_TABLE, part1=CHAT_TURNS_TABLE),
                (normalized_user_id, normalized_session_id),
            )
            .fetchall()
        )
        rhythm_message_ids = {
            (str(row["turn_id"] or "").strip(), int(row["sequence_no"] or 0)): str(
                row["message_id"]
            )
            for row in rows
            if str(row["turn_id"] or "").strip()
            and str(row["message_kind"] or "") == "assistant_rhythm_segment"
        }
        return [
            _message_source_identity_from_row(
                row,
                rhythm_message_ids=rhythm_message_ids,
            )
            for row in rows
        ]

    def create_new_session(
        self,
        user_id: str,
        workspace_path: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id).strip()
        if not normalized_user_id:
            raise ValueError("User ID is required")
        normalized_idempotency_key = str(idempotency_key or "").strip() or None
        if (
            normalized_idempotency_key is not None
            and _SESSION_CREATION_IDEMPOTENCY_KEY_PATTERN.fullmatch(
                normalized_idempotency_key
            )
            is None
        ):
            raise ValueError("Idempotency key is invalid")
        record = create_chat_session_record(
            user_id=normalized_user_id,
            session_id=f"session_{uuid.uuid4()}",
            workspace_path=host._normalize_workspace_path(workspace_path),
        )
        session_id, created = _insert_or_return_session(
            host=host,
            record=record,
            normalized_user_id=normalized_user_id,
            normalized_idempotency_key=normalized_idempotency_key,
        )
        if created:
            claim_workspace_identity(record.workspace_path)
        return session_id

    def get_session_summary(self, user_id: str, session_id: str) -> ChatSessionSummary | None:
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")
        if not host.database.is_present():
            return None
        row = (
            host._get_conn()
            .execute(
                statement("""
            SELECT
                session_id,
                title,
                title_overridden,
                last_message_preview,
                last_user_message_preview,
                workspace_path,
                updated_at_ms,
                last_message_at_ms,
                message_count,
                history_version
            FROM {part0}
            WHERE user_id = ?
              AND session_id = ?
              AND deleted_at_ms IS NULL
              AND archived_at_ms IS NULL
            """, part0=CHAT_SESSIONS_TABLE),
                (normalized_user_id, normalized_session_id),
            )
            .fetchone()
        )
        return host._row_to_session_summary(row) if row is not None else None

    def get_session_summaries_batch(
        self,
        user_id: str,
        session_ids: list[str],
    ) -> dict[str, ChatSessionSummary]:
        """Fetch multiple session summaries in one query."""
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id).strip()
        if not normalized_user_id or not session_ids:
            return {}
        if not host.database.is_present():
            return {}
        clean_ids = [str(sid).strip() for sid in session_ids if str(sid).strip()]
        if not clean_ids:
            return {}
        placeholders = ", ".join("?" for _ in clean_ids)
        rows = (
            host._get_conn()
            .execute(
                statement("""
            SELECT
                session_id,
                title,
                title_overridden,
                last_message_preview,
                last_user_message_preview,
                workspace_path,
                updated_at_ms,
                last_message_at_ms,
                message_count,
                history_version
            FROM {part0}
            WHERE user_id = ?
              AND session_id IN ({part1})
              AND deleted_at_ms IS NULL
              AND archived_at_ms IS NULL
            """, part0=CHAT_SESSIONS_TABLE, part1=placeholders),
                (normalized_user_id, *clean_ids),
            )
            .fetchall()
        )
        return {str(row["session_id"]): host._row_to_session_summary(row) for row in rows}

    def list_sessions(self, user_id: str, limit: int = 30) -> list[ChatSessionSummary]:
        """List recent chat sessions for a user."""
        host = cast(_ChatSessionOperationsHost, self)
        safe_limit = max(1, min(limit, 200))
        if not host.database.is_present():
            return []
        try:
            conn = host._get_conn()
            rows = conn.execute(
                statement("""
                SELECT
                    session_id,
                    title,
                    title_overridden,
                    last_message_preview,
                    last_user_message_preview,
                    workspace_path,
                    updated_at_ms,
                    last_message_at_ms,
                    message_count,
                    history_version
                FROM {part0}
                WHERE user_id = ?
                  AND deleted_at_ms IS NULL
                  AND archived_at_ms IS NULL
                ORDER BY updated_at_ms DESC, created_at_ms DESC
                LIMIT ?
                """, part0=CHAT_SESSIONS_TABLE),
                (user_id, safe_limit),
            ).fetchall()
        except Exception as exc:
            logger.exception(f"Failed to query session list: {exc}")
            raise

        return [host._row_to_session_summary(row) for row in rows]

    def list_workspace_paths(self, user_id: str) -> list[str]:
        """List every distinct workspace used by non-deleted sessions."""
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id).strip()
        if not normalized_user_id or not host.database.is_present():
            return []
        rows = (
            host._get_conn()
            .execute(
                statement("""
            SELECT DISTINCT TRIM(workspace_path) AS workspace_path
            FROM {part0}
            WHERE user_id = ?
              AND deleted_at_ms IS NULL
              AND workspace_path IS NOT NULL
              AND TRIM(workspace_path) != ''
            ORDER BY workspace_path COLLATE NOCASE, workspace_path
            """, mysql="""
            SELECT DISTINCT TRIM(workspace_path) AS workspace_path
            FROM {part0}
            WHERE user_id = ?
              AND deleted_at_ms IS NULL
              AND workspace_path IS NOT NULL
              AND TRIM(workspace_path) != ''
            ORDER BY {fold1}, workspace_path
            """, part0=CHAT_SESSIONS_TABLE, fold1=mysql_ascii_lower('workspace_path')),
                (normalized_user_id,),
            )
            .fetchall()
        )
        return [str(row["workspace_path"]) for row in rows]

    def rename_session(self, user_id: str, session_id: str, title: str) -> ChatSessionRenameResult:
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        normalized_title = str(title).strip()
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")
        if not normalized_title:
            raise ValueError("Session title cannot be empty")
        conn = host._get_conn()
        cur = conn.execute(
            statement("""
            UPDATE {part0}
            SET title = ?, title_overridden = 1, updated_at_ms = CAST(strftime('%s', 'now') AS INTEGER) * 1000
            WHERE session_id = ?
              AND user_id = ?
              AND deleted_at_ms IS NULL
            """, mysql="""
            UPDATE {part0}
            SET title = ?, title_overridden = 1, updated_at_ms = CAST(UNIX_TIMESTAMP() AS SIGNED) * 1000
            WHERE session_id = ?
              AND user_id = ?
              AND deleted_at_ms IS NULL
            """, part0=CHAT_SESSIONS_TABLE),
            (normalized_title, normalized_session_id, normalized_user_id),
        )
        conn.commit()
        if cur.rowcount <= 0:
            raise ChatSessionNotFound("Session not found")
        return ChatSessionRenameResult(session_id=normalized_session_id, title=normalized_title)

    def update_session_workspace(
        self,
        user_id: str,
        session_id: str,
        workspace_path: str | None,
    ) -> SessionWorkspaceUpdateResult:
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        normalized_workspace_path = host._normalize_workspace_path(workspace_path)
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")
        conn = host._get_conn()
        conn.begin_write()
        existing = conn.execute(
            statement("""
            SELECT workspace_path
            FROM {part0}
            WHERE session_id = ?
              AND user_id = ?
              AND deleted_at_ms IS NULL
            """, part0=CHAT_SESSIONS_TABLE),
            (normalized_session_id, normalized_user_id),
        ).fetchone()
        if existing is None:
            conn.rollback()
            raise ChatSessionNotFound("Session not found")
        cur = conn.execute(
            statement("""
            UPDATE {part0}
            SET workspace_path = ?,
                updated_at_ms = CAST(strftime('%s', 'now') AS INTEGER) * 1000
            WHERE session_id = ?
              AND user_id = ?
              AND deleted_at_ms IS NULL
            """, mysql="""
            UPDATE {part0}
            SET workspace_path = ?,
                updated_at_ms = CAST(UNIX_TIMESTAMP() AS SIGNED) * 1000
            WHERE session_id = ?
              AND user_id = ?
              AND deleted_at_ms IS NULL
            """, part0=CHAT_SESSIONS_TABLE),
            (normalized_workspace_path, normalized_session_id, normalized_user_id),
        )
        if cur.rowcount <= 0:
            conn.rollback()
            raise ChatSessionNotFound("Session not found")
        conn.commit()
        claim_workspace_identity(normalized_workspace_path)
        return SessionWorkspaceUpdateResult(
            session_id=normalized_session_id,
            workspace_path=normalized_workspace_path,
        )

    def prepare_session_cleanup(self, user_id: str, session_id: str) -> ChatCleanupPlan | None:
        host = cast(_ChatSessionOperationsHost, self)
        normalized_user_id = str(user_id).strip()
        normalized_session_id = str(session_id).strip()
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")

        conn = host._get_conn()
        conn.begin_write()
        try:
            existing = conn.execute(
                statement("""
                SELECT deleted_at_ms
                FROM {part0}
                WHERE user_id = ? AND session_id = ?
                LIMIT 1
                """, part0=CHAT_SESSIONS_TABLE),
                (normalized_user_id, normalized_session_id),
            ).fetchone()
            if existing is None:
                conn.rollback()
                return None
            conn.execute(
                statement("""
                INSERT OR IGNORE INTO {part0}(
                    session_id,
                    cleared_at_ms
                ) VALUES (
                    ?,
                    CAST(strftime('%s', 'now') AS INTEGER) * 1000
                )
                """, mysql="""
                INSERT IGNORE INTO {part0}(
                    session_id,
                    cleared_at_ms
                ) VALUES (
                    ?,
                    CAST(UNIX_TIMESTAMP() AS SIGNED) * 1000
                )
                """, part0=CHAT_CLEARED_SESSION_SCOPES_TABLE),
                (normalized_session_id,),
            )
            assert_unambiguous_session_asset_scope(
                conn,
                session_id=normalized_session_id,
            )
            message_ids = [
                str(row["message_id"])
                for row in conn.execute(
                    statement("""
                    SELECT message_id
                    FROM {part0}
                    WHERE user_id = ? AND session_id = ?
                    """, part0=CHAT_MESSAGES_TABLE),
                    (normalized_user_id, normalized_session_id),
                ).fetchall()
            ]
            turn_ids = [
                str(row["turn_id"])
                for row in conn.execute(
                    statement("""
                    SELECT turn_id
                    FROM {part0}
                    WHERE user_id = ? AND session_id = ?
                    """, part0=CHAT_TURNS_TABLE),
                    (normalized_user_id, normalized_session_id),
                ).fetchall()
            ]
            candidate_asset_references = host._list_chat_snapshot_asset_references(
                session_id=normalized_session_id,
                turn_ids=turn_ids,
                delete_entire_session=True,
            )
            asset_references = unshared_asset_references(
                conn,
                message_ids=message_ids,
                candidate_asset_references=candidate_asset_references,
            )
            code_delegation_references = (
                unshared_code_delegation_references(
                    conn,
                    message_ids=message_ids,
                    session_id=normalized_session_id,
                )
            )
            delete_session_model_context(
                conn,
                session_id=normalized_session_id,
            )
            if (
                existing["deleted_at_ms"] is not None
                and not message_ids
                and not turn_ids
                and not asset_references
                and not code_delegation_references
            ):
                conn.commit()
                return None
            replace_deletion_scope(
                conn,
                message_ids=message_ids,
                turn_ids=turn_ids,
            )
            retire_turns(conn, turn_ids)
            # The session and transcript become inaccessible before any
            # irreversible file mutation. Private asset references remain as
            # the exact retry ledger until cleanup succeeds.
            redact_scoped_messages(
                conn,
                user_id=normalized_user_id,
                session_id=normalized_session_id,
            )
            conn.execute(
                statement("""DELETE FROM {part0} WHERE user_id = ? AND session_id = ?""", part0=CHAT_ATTACHMENTS_TABLE),
                (normalized_user_id, normalized_session_id),
            )
            conn.execute(
                statement("""DELETE FROM {part0} WHERE session_id = ?""", part0=CHAT_ASSISTANT_MEMORY_OUTBOX_TABLE),
                (normalized_session_id,),
            )
            conn.execute(
                statement("""
                DELETE FROM {part0}
                WHERE turn_id IN (
                    SELECT item_id FROM {part1}
                )
                """, part0=CHAT_USER_TURN_DELIVERY_TABLE, part1=DELETION_TURN_IDS_TABLE)
            )
            conn.execute(
                statement("""DELETE FROM {part0} WHERE session_id = ?""", part0=CHAT_CONTEXT_SUMMARIES_TABLE),
                (normalized_session_id,),
            )
            conn.execute(
                statement("""DELETE FROM {part0} WHERE session_id = ?""", part0=CHAT_CONTEXT_USAGE_SNAPSHOTS_TABLE),
                (normalized_session_id,),
            )
            conn.execute(
                statement("""DELETE FROM {part0} WHERE session_id = ?""", part0=CHAT_RUN_CONSUMED_EVENTS_TABLE),
                (normalized_session_id,),
            )
            conn.execute(
                statement("""
                UPDATE {part0}
                SET title = '',
                    summary = '',
                    last_message_at_ms = NULL,
                    last_user_message_at_ms = NULL,
                    last_message_preview = '',
                    last_user_message_preview = '',
                    message_count = 0,
                    workspace_path = NULL,
                    archived_at_ms = NULL,
                    deleted_at_ms = COALESCE(
                        deleted_at_ms,
                        CAST(strftime('%s', 'now') AS INTEGER) * 1000
                    ),
                    updated_at_ms = CAST(strftime('%s', 'now') AS INTEGER) * 1000,
                    history_version = history_version + ?
                WHERE user_id = ?
                  AND session_id = ?
                """, mysql="""
                UPDATE {part0}
                SET title = '',
                    summary = '',
                    last_message_at_ms = NULL,
                    last_user_message_at_ms = NULL,
                    last_message_preview = '',
                    last_user_message_preview = '',
                    message_count = 0,
                    workspace_path = NULL,
                    archived_at_ms = NULL,
                    deleted_at_ms = COALESCE(
                        deleted_at_ms,
                        CAST(UNIX_TIMESTAMP() AS SIGNED) * 1000
                    ),
                    updated_at_ms = CAST(UNIX_TIMESTAMP() AS SIGNED) * 1000,
                    history_version = history_version + ?
                WHERE user_id = ?
                  AND session_id = ?
                """, part0=CHAT_SESSIONS_TABLE),
                (
                    1 if existing["deleted_at_ms"] is None else 0,
                    normalized_user_id,
                    normalized_session_id,
                ),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

        return ChatCleanupPlan("session", normalized_user_id, normalized_session_id, message_ids, turn_ids, whole_session=True, asset_references=asset_references, code_references=code_delegation_references)

    def finish_session_cleanup(self, plan: ChatCleanupPlan) -> None:
        normalized_user_id, normalized_session_id = plan.user_id, plan.session_id
        message_ids, turn_ids = plan.message_ids, plan.turn_ids
        code_delegation_references = plan.code_references
        conn = cast(_ChatSessionOperationsHost, self)._get_conn()
        conn.begin_write()
        try:
            replace_deletion_scope(
                conn,
                message_ids=message_ids,
                turn_ids=turn_ids,
            )
            delete_scoped_asset_references(conn)
            delete_scoped_code_delegation_references(conn)
            delete_code_delegation_artifact_records(
                conn,
                references=code_delegation_references,
            )
            delete_scoped_message_tombstones(
                conn,
                user_id=normalized_user_id,
                session_id=normalized_session_id,
            )
            conn.execute(
                statement("""
                DELETE FROM {part0}
                WHERE turn_id IN (
                    SELECT item_id FROM {part1}
                )
                """, part0=CHAT_USER_TURN_DELIVERY_TABLE, part1=DELETION_TURN_IDS_TABLE)
            )
            conn.execute(
                statement("""DELETE FROM {part0} WHERE user_id = ? AND session_id = ?""", part0=CHAT_TURNS_TABLE),
                (normalized_user_id, normalized_session_id),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    def prepare_global_cleanup(self) -> ChatCleanupPlan:
        """Clear all chat session rows and return removed count."""
        host = cast(_ChatSessionOperationsHost, self)
        if not host.database.is_present():
            return ChatCleanupPlan("global")
        conn = host._get_conn()
        conn.prepare_content_clear()
        conn.begin_write()
        try:
            code_delegation_references = (
                unshared_code_delegation_references(
                    conn,
                    all_artifacts=True,
                )
            )
            pending = conn.execute(
                statement("""
                SELECT session_count
                FROM {part0}
                WHERE intent_key = 'global'
                LIMIT 1
                """, part0=CHAT_GLOBAL_CLEAR_INTENT_TABLE)
            ).fetchone()
            if pending is not None:
                removed = int(pending["session_count"] or 0)
            else:
                row = conn.execute(
                    statement("""
                    SELECT COUNT(*) AS total
                    FROM {part0}
                    WHERE deleted_at_ms IS NULL
                    """, part0=CHAT_SESSIONS_TABLE)
                ).fetchone()
                removed = int((row["total"] if row is not None else 0) or 0)
            conn.execute(
                statement("""
                INSERT INTO {part0}(
                    intent_key,
                    requested_at_ms,
                    session_count
                ) VALUES (
                    'global',
                    CAST(strftime('%s', 'now') AS INTEGER) * 1000,
                    ?
                )
                ON CONFLICT(intent_key) DO NOTHING
                """, mysql="""
                INSERT IGNORE INTO {part0}(
                    intent_key,
                    requested_at_ms,
                    session_count
                ) VALUES (
                    'global',
                    CAST(UNIX_TIMESTAMP() AS SIGNED) * 1000,
                    ?
                )

                """, part0=CHAT_GLOBAL_CLEAR_INTENT_TABLE),
                (removed,),
            )
            conn.execute(
                statement("""
                INSERT OR IGNORE INTO {part0}(
                    workspace_path,
                    session_id,
                    created_at_ms
                )
                SELECT
                    workspace_path,
                    session_id,
                    CAST(strftime('%s', 'now') AS INTEGER) * 1000
                FROM {part1}
                WHERE TRIM(COALESCE(workspace_path, '')) <> ''
                """, mysql="""
                INSERT IGNORE INTO {part0}(
                    workspace_path,
                    session_id,
                    created_at_ms
                )
                SELECT
                    workspace_path,
                    session_id,
                    CAST(UNIX_TIMESTAMP() AS SIGNED) * 1000
                FROM {part1}
                WHERE TRIM(COALESCE(workspace_path, '')) <> ''
                """, part0=CHAT_WORKSPACE_SESSION_CLEANUP_TABLE, part1=CHAT_SESSIONS_TABLE)
            )
            conn.execute(
                statement("""
                INSERT OR IGNORE INTO {part0}(
                    workspace_path,
                    session_id,
                    created_at_ms
                )
                SELECT
                    workspace_path,
                    session_id,
                    CAST(strftime('%s', 'now') AS INTEGER) * 1000
                FROM {part1}
                WHERE TRIM(workspace_path) <> ''
                """, mysql="""
                INSERT IGNORE INTO {part0}(
                    workspace_path,
                    session_id,
                    created_at_ms
                )
                SELECT
                    workspace_path,
                    session_id,
                    CAST(UNIX_TIMESTAMP() AS SIGNED) * 1000
                FROM {part1}
                WHERE TRIM(workspace_path) <> ''
                """, part0=CHAT_WORKSPACE_SESSION_CLEANUP_TABLE, part1=CHAT_CODE_DELEGATION_ARTIFACTS_TABLE)
            )
            workspace_session_references = [
                WorkspaceSessionArtifactReference(
                    workspace_path=str(row["workspace_path"]),
                    session_id=str(row["session_id"]),
                )
                for row in conn.execute(
                    statement("""
                    SELECT workspace_path, session_id
                    FROM {part0}
                    ORDER BY workspace_path, session_id
                    """, part0=CHAT_WORKSPACE_SESSION_CLEANUP_TABLE)
                ).fetchall()
            ]
            conn.execute(
                statement("""
                INSERT OR IGNORE INTO {part0}(
                    session_id,
                    cleared_at_ms
                )
                SELECT
                    session_id,
                    CAST(strftime('%s', 'now') AS INTEGER) * 1000
                FROM {part1}
                """, mysql="""
                INSERT IGNORE INTO {part0}(
                    session_id,
                    cleared_at_ms
                )
                SELECT
                    session_id,
                    CAST(UNIX_TIMESTAMP() AS SIGNED) * 1000
                FROM {part1}
                """, part0=CHAT_CLEARED_SESSION_SCOPES_TABLE, part1=CHAT_SESSIONS_TABLE)
            )
            retire_turns(conn, (str(row["turn_id"]) for row in conn.execute(
                "SELECT turn_id FROM chat_turns"
            ).fetchall()))
            # Redact every public row first, but retain message rows and private
            # asset references so a failed filesystem cleanup has an exact,
            # idempotent retry path.
            conn.execute(
                statement("""
                UPDATE {part0}
                SET content_text = '',
                    payload_json = '{{}}',
                    is_visible = 0,
                    replaces_message_id = NULL,
                    replaced_by_message_id = NULL,
                    persona_id = NULL,
                    reply_to_message_id = NULL,
                    label_json = NULL
                """, part0=CHAT_MESSAGES_TABLE)
            )
            conn.execute(statement("""DELETE FROM {part0}""", part0=CHAT_ATTACHMENTS_TABLE))
            conn.execute(statement("""DELETE FROM {part0}""", part0=CHAT_ASSISTANT_MEMORY_OUTBOX_TABLE))
            conn.execute(statement("""DELETE FROM {part0}""", part0=CHAT_USER_TURN_DELIVERY_TABLE))
            conn.execute(statement("""DELETE FROM {part0}""", part0=CHAT_CONTEXT_SUMMARIES_TABLE))
            conn.execute(statement("""DELETE FROM {part0}""", part0=CHAT_CONTEXT_USAGE_SNAPSHOTS_TABLE))
            conn.execute(statement("""DELETE FROM {part0}""", part0=CHAT_RUN_CONSUMED_EVENTS_TABLE))
            delete_all_model_context(conn)
            conn.execute(
                statement("""
                UPDATE {part0}
                SET title = '',
                    summary = '',
                    last_message_at_ms = NULL,
                    last_user_message_at_ms = NULL,
                    last_message_preview = '',
                    last_user_message_preview = '',
                    message_count = 0,
                    workspace_path = NULL,
                    archived_at_ms = NULL,
                    deleted_at_ms = COALESCE(
                        deleted_at_ms,
                        CAST(strftime('%s', 'now') AS INTEGER) * 1000
                    ),
                    updated_at_ms = CAST(strftime('%s', 'now') AS INTEGER) * 1000,
                    history_version = history_version + CASE
                        WHEN deleted_at_ms IS NULL THEN 1 ELSE 0
                    END
                """, mysql="""
                UPDATE {part0}
                SET title = '',
                    summary = '',
                    last_message_at_ms = NULL,
                    last_user_message_at_ms = NULL,
                    last_message_preview = '',
                    last_user_message_preview = '',
                    message_count = 0,
                    workspace_path = NULL,
                    archived_at_ms = NULL,
                    deleted_at_ms = COALESCE(
                        deleted_at_ms,
                        CAST(UNIX_TIMESTAMP() AS SIGNED) * 1000
                    ),
                    updated_at_ms = CAST(UNIX_TIMESTAMP() AS SIGNED) * 1000,
                    history_version = history_version + CASE
                        WHEN deleted_at_ms IS NULL THEN 1 ELSE 0
                    END
                """, part0=CHAT_SESSIONS_TABLE)
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

        return ChatCleanupPlan("global", code_references=code_delegation_references, workspace_references=workspace_session_references, removed_count=removed)

    def finish_global_cleanup(self, plan: ChatCleanupPlan) -> None:
        if not cast(_ChatSessionOperationsHost, self).database.is_present():
            return
        conn = cast(_ChatSessionOperationsHost, self)._get_conn()
        conn.begin_write()
        try:
            conn.execute(statement("""DELETE FROM {part0}""", part0=CHAT_WORKSPACE_SESSION_CLEANUP_TABLE))
            conn.execute(statement("""DELETE FROM {part0}""", part0=CHAT_MESSAGE_ASSET_REFS_TABLE))
            conn.execute(
                statement("""DELETE FROM {part0}""", part0=CHAT_MESSAGE_CODE_DELEGATION_REFS_TABLE)
            )
            conn.execute(
                statement("""DELETE FROM {part0}""", part0=CHAT_CODE_DELEGATION_ARTIFACTS_TABLE)
            )
            conn.execute(statement("""DELETE FROM {part0}""", part0=CHAT_MESSAGES_TABLE))
            conn.execute(statement("""DELETE FROM {part0}""", part0=CHAT_TURNS_TABLE))
            conn.execute(statement("""DELETE FROM {part0}""", part0=CHAT_CONTEXT_USAGE_SNAPSHOTS_TABLE))
            conn.execute(
                statement("""DELETE FROM {part0}""", part0=CHAT_SESSION_CREATION_REQUESTS_TABLE)
            )
            conn.execute(statement("""DELETE FROM {part0}""", part0=CHAT_SESSIONS_TABLE))
            conn.execute("DELETE FROM chat_read_revisions")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


    def complete_global_clear(self) -> bool:
        """Release the global barrier after every conversation store is clean."""

        host = cast(_ChatSessionOperationsHost, self)
        if not host.database.is_present():
            return False
        conn = host._get_conn()
        conn.prepare_content_clear()
        conn.begin_write()
        try:
            pending = conn.execute(
                statement("""
                SELECT 1
                FROM {part0}
                WHERE intent_key = 'global'
                LIMIT 1
                """, part0=CHAT_GLOBAL_CLEAR_INTENT_TABLE)
            ).fetchone()
            if pending is None:
                conn.rollback()
                return False
            remaining = conn.execute(
                statement("""
                SELECT
                    (SELECT COUNT(*) FROM {part0})
                  + (SELECT COUNT(*) FROM {part1})
                  + (SELECT COUNT(*) FROM {part2})
                  + (SELECT COUNT(*) FROM {part3})
                  + (SELECT COUNT(*) FROM {part4})
                  + (SELECT COUNT(*) FROM {part5})
                  + (SELECT COUNT(*) FROM {part6})
                  + (SELECT COUNT(*) FROM {part7})
                  + (SELECT COUNT(*) FROM {part8})
                  + (SELECT COUNT(*) FROM {part9})
                  + (SELECT COUNT(*) FROM {part10})
                  + (SELECT COUNT(*) FROM {part11})
                  + (SELECT COUNT(*) FROM {part12})
                  + (SELECT COUNT(*) FROM {part13})
                  + (SELECT COUNT(*) FROM {part14})
                  + (SELECT COUNT(*) FROM {part15})
                  + (SELECT COUNT(*) FROM {part16})
                  + (SELECT COUNT(*) FROM {part17})
                  + (SELECT COUNT(*) FROM {part18})
                  + (SELECT COUNT(*) FROM {part19})
                """, part0=CHAT_SESSIONS_TABLE, part1=CHAT_TURNS_TABLE, part2=CHAT_MESSAGES_TABLE, part3=CHAT_ATTACHMENTS_TABLE, part4=CHAT_MESSAGE_ASSET_REFS_TABLE, part5=CHAT_MESSAGE_CODE_DELEGATION_REFS_TABLE, part6=CHAT_CODE_DELEGATION_ARTIFACTS_TABLE, part7=CHAT_WORKSPACE_SESSION_CLEANUP_TABLE, part8=CHAT_ASSISTANT_MEMORY_OUTBOX_TABLE, part9=CHAT_USER_TURN_DELIVERY_TABLE, part10=CHAT_CONTEXT_SUMMARIES_TABLE, part11=CHAT_CONTEXT_USAGE_SNAPSHOTS_TABLE, part12=CHAT_RUN_CONSUMED_EVENTS_TABLE, part13=CHAT_MODEL_CONTEXT_HEADS_TABLE, part14=CHAT_MODEL_CONTEXT_EVENTS_TABLE, part15=CHAT_MODEL_CONTEXT_REVISIONS_TABLE, part16=CHAT_MODEL_CONTEXT_SURFACE_NODES_TABLE, part17=CHAT_MODEL_CONTEXT_RUN_HEADS_TABLE, part18=CHAT_MODEL_CONTEXT_EPOCHS_TABLE, part19=CHAT_MODEL_CONTEXT_BOUNDARIES_TABLE)
            ).fetchone()
            if remaining is None or int(remaining[0] or 0) != 0:
                raise RuntimeError(
                    "Global chat clear cannot complete while chat rows remain"
                )
            conn.execute(statement("""DELETE FROM {part0}""", part0=CHAT_CLEARED_MESSAGE_SCOPES_TABLE))
            conn.execute(statement("""DELETE FROM {part0}""", part0=CHAT_CLEARED_SESSION_SCOPES_TABLE))
            conn.commit()

            conn.compact_cleared_content()
            conn.checkpoint_cleared_content()

            conn.begin_write()
            conn.execute(
                statement("""
                DELETE FROM {part0}
                WHERE intent_key = 'global'
                """, part0=CHAT_GLOBAL_CLEAR_INTENT_TABLE)
            )
            conn.commit()
            conn.checkpoint_cleared_content()
            return True
        except BaseException:
            conn.rollback()
            raise

    def get_interrupted_global_clear_count(self) -> int | None:
        """Return the committed clear count while physical cleanup is pending."""

        host = cast(_ChatSessionOperationsHost, self)
        if not host.database.is_present():
            return None
        row = host._get_conn().execute(
            statement("""
            SELECT session_count
            FROM {part0}
            WHERE intent_key = 'global'
            LIMIT 1
            """, part0=CHAT_GLOBAL_CLEAR_INTENT_TABLE)
        ).fetchone()
        return int(row["session_count"] or 0) if row is not None else None

    def reset_user_turn_delivery_after_failed_clear(self) -> int:
        """Make surviving chat turns replayable after a partial global clear."""
        host = cast(_ChatSessionOperationsHost, self)
        if not host.database.is_present():
            return 0
        conn = host._get_conn()
        conn.begin_write()
        try:
            cursor = conn.execute(statement("""
                UPDATE {part0}
                SET projection_completed = 0,
                    delivery_attempt_no = delivery_attempt_no + 1,
                    delivery_state = 'ready',
                    current_command_id = NULL,
                    updated_at_ms = CAST(strftime('%s', 'now') AS INTEGER) * 1000
                WHERE delivery_state IN ('ready', 'queued', 'admitted')
                """, mysql="""
                UPDATE {part0}
                SET projection_completed = 0,
                    delivery_attempt_no = delivery_attempt_no + 1,
                    delivery_state = 'ready',
                    current_command_id = NULL,
                    updated_at_ms = CAST(UNIX_TIMESTAMP() AS SIGNED) * 1000
                WHERE delivery_state IN ('ready', 'queued', 'admitted')
                """, part0=CHAT_USER_TURN_DELIVERY_TABLE))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return int(cursor.rowcount or 0)


__all__ = ["ChatSessionOperationsMixin"]
