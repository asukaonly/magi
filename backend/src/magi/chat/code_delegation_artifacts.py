"""Durable registration for code-agent artifacts owned by chat turns."""

from __future__ import annotations

import time
from typing import Any

from ..core.code_agent_artifacts import (
    CodeAgentDelegationReference,
    normalize_code_agent_delegation_references,
)
from .ownership_ports import ChatArtifactRepository


class ChatCodeDelegationArtifactRegistry:
    """Register private code-agent artifacts before filesystem writes begin."""

    def __init__(self, *, repository: ChatArtifactRepository) -> None:
        self._repository = repository

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
        await self._repository.register_code_artifact(reference, created_at_ms=int(time.time() * 1000))

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
