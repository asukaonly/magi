"""Resolve immutable output addresses before any provider invocation."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from magi_plugin_sdk.channels import ChannelTarget as ChannelTarget
from magi_plugin_sdk.endpoints import EndpointRef

from magi_plugin_sdk.storage_models.delivery_plan import (
    DeliveryPlan,
)

DeliveryTargetValidator = Callable[[tuple[EndpointRef, ...]], Awaitable[None]]




def build_delivery_plan(
    *, session_id: str, user_id: str, reply_to: EndpointRef | None = None,
    user_prefs: dict[str, Any] | None = None,
) -> DeliveryPlan:
    """Keep conversation updates distinct from explicit external destinations.

    Native conversation synchronization remains available to connected viewers.
    Additional destinations and external replies always contain actual addresses;
    a channel never has to guess an external recipient from a session ID.
    """
    if not session_id or not user_id:
        raise ValueError("Delivery routing requires a session and user")
    preferences = user_prefs or {}
    configured = preferences.get("delivery_targets", [])
    if not isinstance(configured, list) or len(configured) > 32:
        raise ValueError("Delivery targets must be a list of at most 32 endpoint references")
    native = EndpointRef(None, "chat_sse", session_id)
    targets = [native]
    for value in configured:
        endpoint = EndpointRef.from_dict(value)
        if endpoint.registry_key == "chat_sse":
            if endpoint.target_id != session_id:
                raise ValueError("Conversation synchronization cannot target another session")
            continue
        if endpoint not in targets:
            targets.append(endpoint)
    if reply_to is not None and reply_to.registry_key != "chat_sse" and reply_to not in targets:
        targets.append(reply_to)
    return DeliveryPlan(session_id=session_id, user_id=user_id, targets=tuple(targets))
