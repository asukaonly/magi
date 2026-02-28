"""
Stub capability handlers for future action-layer extensions.
"""
from __future__ import annotations

from typing import Any, Dict

from ..contracts import LayerContext, LayerResult
from ..types import StubCapability


class StubActionCapabilities:
    """Returns deterministic placeholders for not-yet-implemented actions."""

    async def execute(self, capability: StubCapability, context: LayerContext) -> LayerResult:
        payload: Dict[str, Any] = {
            "capability": capability.value,
            "message": (
                f"Capability '{capability.value}' is reserved and not implemented yet. "
                "Chat flow remains available."
            ),
            "user_id": context.user_id,
            "session_id": context.session_id,
        }
        return LayerResult(
            success=True,
            payload=payload,
            deferred=True,
            stub_capability=capability,
        )
