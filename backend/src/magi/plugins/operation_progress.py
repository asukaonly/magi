"""Operation progress publication through the existing durable notification bus."""

from __future__ import annotations

from typing import Any

from magi_plugin_sdk.runtime import InvocationIdentity

from ..runtime_trace.notification_payloads import build_notification_record
from ..runtime_trace.provider import resolve_runtime_trace_store


async def publish_operation_progress(
    identity: InvocationIdentity, payload: dict[str, Any]
) -> None:
    """Persist a bounded, host-attributed progress event for the desktop bridge."""
    store = resolve_runtime_trace_store()
    await store.append_notification(
        build_notification_record(
            channel="plugin_operation_progress",
            user_id=identity.principal_id,
            session_id=identity.session_id or "",
            payload={
                "invocation": identity.model_dump(mode="json"),
                "progress": payload,
            },
        )
    )


__all__ = ["publish_operation_progress"]
