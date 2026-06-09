"""Trigger seam (ADR-0004 P3): build RunTriggers from source signals.

Standalone home for the ``source → RunTrigger`` classification that previously
lived as private static methods on chat's ``SessionRunCoordinator``. Keeping it
here (agent core, not chat) lets every surface — chat, scheduler, batch, inbound
channels — build ``RunTrigger``s without importing chat.

This is the first piece of the trigger seam: a pure, side-effect-free factory.
The lifecycle/storage side (who holds the trigger, how it travels with a
``RunRequest``) is addressed in later steps.
"""
from __future__ import annotations

from magi_plugin_sdk.run_trigger import RunTrigger

# Dispatcher ``source`` strings that count as "native magi chat" (HTTP /chat,
# chat UI). Anything else (telegram / weixin / slack / ...) is an external
# inbound channel.
MAGI_NATIVE_SOURCES = frozenset({"api", "magi-chat", "chat_sse"})


def is_external_source(source: str | None) -> bool:
    """Classify a dispatcher ``source`` string.

    Empty/whitespace counts as native (matches the legacy default in
    ``UserMessagePayload``). Case-insensitive so plugins using ``"Telegram"``
    still classify correctly.
    """
    normalized = (source or "api").strip().lower()
    if not normalized:
        return False
    return normalized not in MAGI_NATIVE_SOURCES


def build_user_message_trigger(
    *,
    source: str | None,
    requester: str,
    content: str | None,
    turn_id: str | None,
) -> RunTrigger:
    """Build a source-aware ``RunTrigger`` for a fresh user-message run.

    - native source (``MAGI_NATIVE_SOURCES``) → ``user_message`` with
      ``source_channel="chat_sse"``.
    - any other source → ``external_inbound`` with ``source_channel`` set to the
      (lowercased) dispatcher source so downstream consumers can reason about
      provenance.
    """
    correlation = [turn_id] if turn_id else []
    payload = {"content": content} if content else {}
    if is_external_source(source):
        return RunTrigger(
            trigger_type="external_inbound",
            source_channel=(source or "").strip().lower(),
            requester=requester,
            priority="foreground",
            correlation=correlation,
            payload=payload,
        )
    return RunTrigger(
        trigger_type="user_message",
        source_channel="chat_sse",
        requester=requester,
        priority="foreground",
        correlation=correlation,
        payload=payload,
    )


__all__ = ["MAGI_NATIVE_SOURCES", "is_external_source", "build_user_message_trigger"]
