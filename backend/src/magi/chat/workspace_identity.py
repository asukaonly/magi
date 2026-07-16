"""Workspace identity claims owned by chat persistence boundaries."""

from __future__ import annotations

from pathlib import Path

from ..core.logger import get_logger
from ..core.sqlite import connect_sqlite
from ..core.workspace import WorkspacePaths, WorkspaceStateStore

logger = get_logger(__name__)


def claim_workspace_identity(workspace_path: str | None) -> bool:
    """Persist a durable identity when chat commits a workspace association."""
    normalized_path = str(workspace_path or "").strip()
    if not normalized_path:
        return False
    try:
        paths = WorkspacePaths.from_root(normalized_path)
        if not paths.workspace_root.is_dir():
            return False
        WorkspaceStateStore(paths).claim_identity()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to claim workspace identity",
            error_type=type(exc).__name__,
        )
        return False


def claim_existing_session_workspaces(chat_db_path: str | Path) -> int:
    """Claim identities from existing non-deleted chat session workspaces."""
    db_path = Path(chat_db_path)
    if not db_path.exists():
        return 0
    try:
        connection = connect_sqlite(db_path, profile="mixed")
        try:
            rows = connection.execute(
                """
                SELECT DISTINCT TRIM(workspace_path) AS workspace_path
                FROM chat_sessions
                WHERE deleted_at_ms IS NULL
                  AND workspace_path IS NOT NULL
                  AND TRIM(workspace_path) != ''
                ORDER BY workspace_path COLLATE NOCASE, workspace_path
                """
            ).fetchall()
        finally:
            connection.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to load existing chat workspaces for identity claims",
            error_type=type(exc).__name__,
        )
        return 0
    return sum(claim_workspace_identity(str(row["workspace_path"])) for row in rows)


__all__ = [
    "claim_existing_session_workspaces",
    "claim_workspace_identity",
]
