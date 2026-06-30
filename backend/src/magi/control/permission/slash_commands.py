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

#: Slash-style: ``/approve [short_id]``, ``/deny [short_id]``, plus
#: Chinese / English aliases. short_id is optional — when missing,
#: we resolve the single pending request in the session (most common
#: case: user sees prompt, taps reply, types "同意"). Case-insensitive
#: ASCII verb; Chinese verbs handled separately.
_SLASH_PATTERN = re.compile(
    r"^\s*/(approve|allow|deny|reject)\s*([a-zA-Z0-9]+)?\s*$",
    re.IGNORECASE,
)

#: Natural-language verbs (no slash prefix). ONLY matched when a
#: pending request exists in the session — otherwise these words
#: are normal chat. The optional short_id suffix lets users target
#: a specific request when multiple are pending.
_NATURAL_PATTERN = re.compile(
    r"^\s*(同意|批准|允许|好的?|行|可以|approve|allow|ok|yes|y|"
    r"拒绝|不要?|不行|不可以|deny|reject|no|n)\s*([a-zA-Z0-9]+)?\s*$",
    re.IGNORECASE,
)

_APPROVE_VERBS = {
    "approve",
    "allow",
    "ok",
    "yes",
    "y",
    "同意",
    "批准",
    "允许",
    "好",
    "好的",
    "行",
    "可以",
}
_DENY_VERBS = {
    "deny",
    "reject",
    "no",
    "n",
    "拒绝",
    "不",
    "不要",
    "不行",
    "不可以",
}


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


@dataclass(frozen=True, slots=True)
class _ParsedControlCommand:
    verb: str
    short_id: str | None
    is_allow: bool


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

    Three parse phases:
      1. Slash pattern (``/approve [short_id]``) — always tries to
         handle, even without a short_id (resolves the single
         pending request in scope).
      2. Natural-language pattern (``同意``, ``ok``, ``yes``, ``拒绝``,
         ``no`` …) — ONLY when there's a pending request in scope;
         otherwise treated as chat to avoid false positives on
         common words.
      3. Falls through to chat dispatch.
    """
    text = message.strip()
    if not text:
        return ControlCommandOutcome(handled=False)

    command = _parse_slash_command(text)
    if command is None:
        command = _parse_natural_command(
            text=text,
            session_id=session_id,
            registry=registry,
        )
    if command is None:
        return ControlCommandOutcome(handled=False)

    return await _resolve_parsed_command(
        command=command,
        session_id=session_id,
        registry=registry,
        broker=broker,
    )


def _parse_slash_command(text: str) -> _ParsedControlCommand | None:
    slash_match = _SLASH_PATTERN.match(text)
    if not slash_match:
        return None
    verb = slash_match.group(1).lower()
    return _ParsedControlCommand(
        verb=verb,
        short_id=slash_match.group(2),
        is_allow=verb in _APPROVE_VERBS,
    )


def _parse_natural_command(
    *,
    text: str,
    session_id: str | None,
    registry: PendingPermissionRegistry,
) -> _ParsedControlCommand | None:
    # SAFETY GATE: without a pending request, words like "好的" stay chat.
    if not registry.snapshot(session_id=session_id):
        return None

    natural_match = _NATURAL_PATTERN.match(text)
    if not natural_match:
        return None
    verb = natural_match.group(1).lower()
    return _ParsedControlCommand(
        verb=verb,
        short_id=natural_match.group(2),
        is_allow=verb in _APPROVE_VERBS,
    )


async def _resolve_parsed_command(
    *,
    command: _ParsedControlCommand,
    session_id: str | None,
    registry: PendingPermissionRegistry,
    broker: InteractionBroker,
) -> ControlCommandOutcome:
    return await _resolve_with_optional_short_id(
        verb=command.verb,
        short_id=command.short_id,
        is_allow=command.is_allow,
        session_id=session_id,
        registry=registry,
        broker=broker,
    )


async def _resolve_with_optional_short_id(
    *,
    verb: str,
    short_id: str | None,
    is_allow: bool,
    session_id: str | None,
    registry: PendingPermissionRegistry,
    broker: InteractionBroker,
) -> ControlCommandOutcome:
    """Shared resolve helper.

    If ``short_id`` is None or empty, finds THE one pending request
    in the session. With multiple pending, returns a friendly ack
    asking the user to disambiguate.
    """
    short_id_clean = (short_id or "").strip().lower()

    if short_id_clean:
        found = registry.find_by_short_id(
            short_id_clean,
            session_id=session_id,
        )
    else:
        pending = registry.snapshot(session_id=session_id)
        if not pending:
            return ControlCommandOutcome(
                handled=True,
                ack_message="当前没有待审批的请求。",
            )
        if len(pending) > 1:
            ids = ", ".join(p.short_id for p in pending)
            return ControlCommandOutcome(
                handled=True,
                ack_message=(f"有多个待审批请求,请指定 ID:\n" f"  /{verb} <ID>\n" f"待审批: {ids}"),
            )
        found = pending[0]

    if found is None:
        return ControlCommandOutcome(
            handled=True,
            ack_message=(
                f"找不到待审批的请求 {short_id_clean} —— " f"可能已超时,或已在其他端处理。"
            ),
        )

    response = UserPromptResponse(
        allow=is_allow,
        scope=PermissionScope.ONE_SHOT,
        matcher=None,
        note=f"channel slash command ({verb})",
    )
    await broker.resolve(
        interaction_id=found.request_id,
        kind="permission",
        response=response,
    )
    verb_display = "同意" if is_allow else "拒绝"
    return ControlCommandOutcome(
        handled=True,
        ack_message=f"✓ 已{verb_display}工具 {found.tool_name}",
        resolved_request_id=found.request_id,
        allowed=is_allow,
    )


__all__ = ["ControlCommandOutcome", "try_handle_control_command"]
