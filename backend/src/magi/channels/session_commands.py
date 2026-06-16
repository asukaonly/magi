"""Channel new-session command — host-side parser + handler.

Lets a channel user (WeChat/Telegram/any) reset their chat's session binding so
the NEXT inbound message starts a fresh magi session. Old history is preserved —
deleting the ``(channel_type, external_chat_id) → session`` mapping merely unlinks
it; the next message's ``ChannelSessionMapper.resolve_or_create`` re-creates a
brand-new session (re-populating the mapping's metadata from that message). The
command itself produces no LLM turn and is not persisted (same short-circuit as
the permission ``/approve`` commands).

Lives in the channels layer (not ``control/permission``) because session reset is
a channels concern. A small step toward issue #5 (channel command unification);
deliberately NOT a generic command registry (YAGNI).

The dispatcher passes a ``ChannelSessionMapper`` (duck-typed as ``Any`` to avoid an
import-layer coupling). ``None`` disables the command (legacy / tests), and the
message then passes through to normal dispatch.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..core.logger import get_logger

logger = get_logger(__name__)

#: Whole-message slash command (case-insensitive ASCII; Chinese has no case).
_SLASH_PATTERN = re.compile(r"^\s*/(?:new|reset|新会话|重置)\s*$", re.IGNORECASE)

#: Whole-message (trimmed) exact phrases — NO substring matching, so normal chat
#: that merely mentions "新会话" is not swallowed.
_EXACT_PHRASES = frozenset({"新会话", "新对话", "重新开始", "重置会话"})

#: Hardcoded ack — matches the existing permission slash-command ack convention
#: (also hardcoded Chinese rather than i18n; migrate together if/when i18n'd).
_ACK_MESSAGE = "✨ 已重置 —— 你的下一条消息会开启全新对话(之前的历史保留、不带入)。"


@dataclass
class SessionCommandOutcome:
    """Result of the new-session command check.

    ``handled=True`` — the message was a new-session command (no LLM turn; the
    dispatcher surfaces ``ack_message`` to the user). ``handled=False`` — not a
    command, or reset wasn't possible; dispatch normally.
    """

    handled: bool
    ack_message: str | None = None


def is_new_session_command(message: str) -> bool:
    """True if the WHOLE message is a new-session command (slash or exact phrase)."""
    text = (message or "").strip()
    if not text:
        return False
    if _SLASH_PATTERN.match(text):
        return True
    return text in _EXACT_PHRASES


async def try_handle_session_command(
    *,
    message: str,
    session_id: str | None,
    session_mapper: Any,
) -> SessionCommandOutcome:
    """Reset the channel→session binding when ``message`` is a new-session command.

    Resolves ``(channel_type, external_chat_id)`` for ``session_id`` via
    ``lookup_by_session`` and deletes that mapping, so the next inbound message
    creates a fresh session. Idempotent when no mapping is found. Returns
    ``handled=False`` (pass-through) when it isn't a command, or when there's no
    ``session_mapper`` / ``session_id`` to act on.
    """
    if not is_new_session_command(message):
        return SessionCommandOutcome(handled=False)
    if session_mapper is None or not session_id:
        # No channel-mapping context to reset — don't swallow the message.
        return SessionCommandOutcome(handled=False)

    try:
        mapping = await session_mapper.lookup_by_session(session_id)
    except Exception:  # noqa: BLE001 — lookup failure must not break dispatch
        logger.debug("session_command.lookup_failed", exc_info=True)
        mapping = None

    if mapping is None:
        # Already reset, or this session isn't channel-bound — idempotent ack.
        return SessionCommandOutcome(handled=True, ack_message=_ACK_MESSAGE)

    try:
        await session_mapper.delete_mapping(
            mapping.channel_type, mapping.external_chat_id,
        )
    except Exception:  # noqa: BLE001 — a failed unbind must not block the user
        logger.debug("session_command.delete_failed", exc_info=True)
        # Still ack success; worst case the user retries.
    else:
        logger.info(
            "session_command.reset",
            session_id=session_id,
            channel_type=getattr(mapping, "channel_type", None),
        )

    return SessionCommandOutcome(handled=True, ack_message=_ACK_MESSAGE)


__all__ = [
    "SessionCommandOutcome",
    "is_new_session_command",
    "try_handle_session_command",
]
