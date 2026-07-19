"""Durable registration for code-agent artifacts owned by chat turns."""

from __future__ import annotations

import time
from typing import Any

from ..core.code_agent_artifacts import (
    CodeAgentDelegationReference,
    normalize_code_agent_delegation_references,
)
from ..core.sqlite import sqlite_connection_async
from ..utils.runtime import RuntimePaths, get_runtime_paths


class ChatCodeDelegationArtifactRegistry:
    """Register private code-agent artifacts before filesystem writes begin."""

    def __init__(self, *, runtime_paths: RuntimePaths | None = None) -> None:
        paths = runtime_paths or get_runtime_paths()
        self._chat_db_path = str(paths.chat_db_path)

    async def register(
        self,
        *,
        session_id: str,
        turn_id: str,
        delegation_id: str,
        workspace_path: str,
    ) -> None:
        """Persist one exact cleanup identity before the delegation starts."""

        reference = self._normalize_reference(
            session_id=session_id,
            turn_id=turn_id,
            delegation_id=delegation_id,
            workspace_path=workspace_path,
        )
        async with sqlite_connection_async(
            self._chat_db_path,
            profile="mixed",
        ) as db:
            await db.execute(
                """
                INSERT INTO chat_code_delegation_artifacts(
                    workspace_path,
                    session_id,
                    delegation_id,
                    turn_id,
                    created_at_ms
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workspace_path, session_id, delegation_id)
                DO UPDATE SET turn_id = excluded.turn_id
                """,
                (
                    reference.workspace_path,
                    reference.session_id,
                    reference.delegation_id,
                    reference.turn_id,
                    int(time.time() * 1000),
                ),
            )
            await db.commit()

    @staticmethod
    def _normalize_reference(
        *,
        session_id: Any,
        turn_id: Any,
        delegation_id: Any,
        workspace_path: Any,
    ) -> CodeAgentDelegationReference:
        references = normalize_code_agent_delegation_references(
            {
                "code_agent_delegations": [
                    {
                        "delegation_id": delegation_id,
                        "turn_id": turn_id,
                        "workspace_path": workspace_path,
                    }
                ]
            },
            session_id=session_id,
        )
        if not references:
            raise ValueError("Code delegation artifact identity is invalid")
        return references[0]


__all__ = ["ChatCodeDelegationArtifactRegistry"]
