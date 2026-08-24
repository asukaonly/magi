"""Explicit permission doubles for agent runtime tests."""

from __future__ import annotations

from magi.control.permission import PermissionDecision, PermissionOutcome, PermissionRequest


class AllowAllPermissionGateway:
    """Allow test tool calls without weakening production defaults."""

    async def gate(self, **_kwargs: object) -> PermissionDecision:
        return PermissionDecision(
            request_id=PermissionRequest.new_id(),
            outcome=PermissionOutcome.ALLOWED,
            source="test",
            reason="explicit test permission gateway",
        )


__all__ = ["AllowAllPermissionGateway"]
