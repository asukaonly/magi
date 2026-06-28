"""Final response delivery planning for chat post-processing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class FinalResponseDeliveryPlan:
    """Notification and delivery shape for a completed chat response."""

    response_text: str
    message_id: str | None
    message_kind: str | None
    persona_id: str | None
    final_message: Any | None


class ResolveReactionText(Protocol):
    def __call__(self, ux_plan: dict[str, Any] | None, *, fallback: str) -> str: ...


def build_final_response_delivery_plan(
    *,
    response_text: str,
    ux_plan: dict[str, Any] | None,
    notification_message: Any | None,
    fallback_persona_id: str | None,
    resolve_reaction_text: ResolveReactionText,
) -> FinalResponseDeliveryPlan:
    """Build the user-visible notification shape after chat outcome persistence."""
    if str((ux_plan or {}).get("assistant_surface_mode") or "").strip() == "reaction_only":
        return FinalResponseDeliveryPlan(
            response_text=resolve_reaction_text(ux_plan, fallback=response_text),
            message_id=None,
            message_kind="assistant_reaction",
            persona_id=str(fallback_persona_id or "").strip() or None,
            final_message=None,
        )

    message_kind = (
        str(getattr(notification_message, "message_kind", "") or "").strip() or None
        if notification_message is not None
        else None
    )
    return FinalResponseDeliveryPlan(
        response_text=response_text,
        message_id=(
            str(getattr(notification_message, "message_id", "") or "").strip() or None
            if notification_message is not None
            else None
        ),
        message_kind=message_kind,
        persona_id=(
            str(getattr(notification_message, "persona_id", "") or "").strip() or None
            if notification_message is not None
            else str(fallback_persona_id or "").strip() or None
        ),
        final_message=(
            notification_message
            if notification_message is not None and message_kind == "assistant_final"
            else None
        ),
    )
