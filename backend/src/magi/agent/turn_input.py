"""Strongly-typed carrier for the user-side input of a chat turn.

Bundles the user-typed text with its already-resolved attachments and the
session identity needed to materialize them. Anything that builds prompt
messages for a chat turn consumes one of these — the type prevents callers
from forgetting to plumb attachments alongside the text.

Attachments here are expected to already be resolved (e.g. MCP resources
expanded into ``resolved_text``); construction does no IO.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class UserTurnInput:
    text: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    user_id: str | None = None
    session_id: str | None = None
