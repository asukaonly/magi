"""Workspace identity claims owned by chat persistence boundaries."""

from __future__ import annotations

from collections.abc import Iterable

from ..core.logger import get_logger
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


def claim_existing_session_workspaces(workspace_paths: Iterable[str]) -> int:
    """Claim identities from the repository's active workspace projection."""
    return sum(claim_workspace_identity(path) for path in workspace_paths)


__all__ = [
    "claim_existing_session_workspaces",
    "claim_workspace_identity",
]
