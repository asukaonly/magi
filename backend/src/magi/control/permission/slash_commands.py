"""Slash-command parser for inbound channel messages.

Minimal subset of issue #5 (channel slash command unification) —
recognizes ``/approve <short_id>`` and ``/deny <short_id>`` and
resolves the corresponding pending :class:`PermissionRequest` via
``InteractionBroker.resolve``. Other slash commands pass through
unchanged (the parser returns None, the caller dispatches normally
to the LLM).

Wired at the ``ChannelMessageDispatcher`` entry point so the
command is short-circuited before any LLM dispatch happens — the
user typing ``/approve abc123`` never produces a turn / message in
the conversation log.

Why this lives in ``magi.control.permission`` and not
``magi.channels`` despite being inbound-message logic: the parser
mutates broker state (resolves the pending interaction), which is
a control-plane concern. The channels layer just hands the message
text in and observes the boolean outcome.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..common.interaction_broker import InteractionBroker
from .brokered_prompter import PendingPermissionRegistry
from .contracts import PermissionScope
from .gateway import UserPromptResponse

#: Matches ``/approve abc123`` and ``/deny abc123`` (and the aliases
#: ``/allow`` / ``/reject``). Case-insensitive verb; ``short_id`` is
#: lowercased before lookup. Only matches when the slash command is
#: the WHOLE message — ``"hello /approve abc"`` is treated as chat,
#: not a command.
_PATTERN = re.compile(
    r"^\s*/(approve|allow|deny|reject)\s+([a-zA-Z0-9]+)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ControlCommandOutcome:
    """Result of attempting to handle a message as a control command.

    ``handled=True`` — the message matched the slash-command pattern.
    The caller MUST NOT dispatch the message to the LLM (it's a
    control action, not chat). ``ack_message`` is a short string the
    caller MAY surface to the user (e.g. "✓ approved" / "request not
    found"); the caller may also choose to silently swallow on
    success and only ack on user-error cases.

    ``handled=False`` — the message wasn't a control command (or the
    parser was disabled). Dispatch normally.
    """

    handled: bool
    ack_message: str | None = None
    resolved_request_id: str | None = None
    allowed: bool | None = None


async def try_handle_control_command(
    *,
    message: str,
    session_id: str | None,
    registry: PendingPermissionRegistry,
    broker: InteractionBroker,
) -> ControlCommandOutcome:
    """Parse ``message`` as a control command and resolve it.

    Returns ``ControlCommandOutcome(handled=False, ...)`` if the
    message isn't a control command — the caller continues with the
    normal LLM dispatch flow.

    On a syntactically-valid command:
    * Looks up the matching pending request via
      ``registry.find_by_short_id(short_id, session_id=session_id)``.
    * If found, calls ``broker.resolve(...)`` to unblock the
      permission gateway with the user's decision. The
      function-calling executor then proceeds with (or aborts) the
      tool call as if the desktop had answered.
    * If not found (timed out / already answered by another channel
      / typo), returns a user-friendly ack so the caller can tell
      the user.

    Cross-session isolation is enforced by the registry — a
    ``/approve`` from session A never resolves a pending request
    raised in session B, even if short_ids collide.
    """
    match = _PATTERN.match(message)
    if not match:
        return ControlCommandOutcome(handled=False)

    verb = match.group(1).lower()
    short_id = match.group(2).lower()
    is_allow = verb in ("approve", "allow")

    found = registry.find_by_short_id(short_id, session_id=session_id)
    if found is None:
        return ControlCommandOutcome(
            handled=True,
            ack_message=(
                f"找不到待审批的请求 {short_id} —— 可能已超时,或已在其他端处理。"
            ),
        )

    response = UserPromptResponse(
        allow=is_allow,
        scope=PermissionScope.ONE_SHOT,
        matcher=None,
        note=f"channel slash command (/{verb})",
    )
    await broker.resolve(
        interaction_id=found.request_id,
        kind="permission",
        response=response,
    )
    verb_display = "同意" if is_allow else "拒绝"
    return ControlCommandOutcome(
        handled=True,
        ack_message=f"✓ 已{verb_display}工具 {found.tool_name} ({short_id})",
        resolved_request_id=found.request_id,
        allowed=is_allow,
    )


__all__ = ["ControlCommandOutcome", "try_handle_control_command"]
