"""Shared chat persistence contracts and value codecs."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re
from magi_plugin_sdk.storage_models.chat_asset_keys import normalize_chat_asset_component


_DELEGATION_ID_PATTERN = re.compile(r"[0-9a-fA-F]{32}")


class CodeAgentArtifactPathError(ValueError):
    """Raised when a code-delegation path cannot be proven to stay in scope."""


@dataclass(frozen=True, slots=True)
class WorkspaceSessionArtifactReference:
    """Exact workspace-owned session cache that must be removed."""

    workspace_path: str
    session_id: str


def normalize_code_agent_delegation_id(value: object) -> str:
    """Return one canonical delegation id that is safe as a path component."""

    normalized = str(value or "").strip()
    if not _DELEGATION_ID_PATTERN.fullmatch(normalized):
        raise CodeAgentArtifactPathError(
            "delegation_id must be a 32-character hexadecimal value"
        )
    return normalized.lower()


@dataclass(frozen=True, slots=True)
class CodeAgentDelegationReference:
    """Stable identity required to recover or remove one code delegation."""

    session_id: str
    delegation_id: str
    turn_id: str
    workspace_path: str

    def to_message_payload(self) -> dict[str, str]:
        """Return the session-local representation persisted on chat messages."""

        return {
            "delegation_id": self.delegation_id,
            "turn_id": self.turn_id,
            "workspace_path": self.workspace_path,
        }


def normalize_code_agent_delegation_references(
    payload: Any,
    *,
    session_id: object,
) -> list[CodeAgentDelegationReference]:
    """Parse the explicit message contract without accepting path-like IDs."""

    if not isinstance(payload, dict):
        return []
    try:
        normalized_session_id = normalize_chat_asset_component(
            session_id,
            label="session_id",
        )
    except ValueError:
        return []
    raw_references = payload.get("code_agent_delegations")
    if not isinstance(raw_references, list):
        return []

    references: list[CodeAgentDelegationReference] = []
    seen: set[str] = set()
    for raw_reference in raw_references:
        if not isinstance(raw_reference, dict):
            continue
        turn_id = str(raw_reference.get("turn_id") or "").strip()
        workspace_path = str(raw_reference.get("workspace_path") or "").strip()
        try:
            normalized_delegation_id = normalize_code_agent_delegation_id(
                raw_reference.get("delegation_id")
            )
        except CodeAgentArtifactPathError:
            continue
        if not turn_id or not workspace_path:
            continue
        if not Path(workspace_path).expanduser().is_absolute():
            continue
        if normalized_delegation_id in seen:
            continue
        seen.add(normalized_delegation_id)
        references.append(
            CodeAgentDelegationReference(
                session_id=normalized_session_id,
                delegation_id=normalized_delegation_id,
                turn_id=turn_id,
                workspace_path=workspace_path,
            )
        )
    return references
