"""Resolve which surfaces an OutreachIntent should reach (deterministic)."""
from __future__ import annotations

from typing import Any, Callable

from magi_plugin_sdk.channels import ChannelTarget

from ..core.logger import get_logger
from .contracts import OutreachIntent, ResolvedTargets

logger = get_logger(__name__)


class TargetResolver:
    """Desktop = origin session if it still exists; external = origin
    external channel (via reverse session mapping), if any. No presence
    signal exists, so routing is origin + validity only (see spec D3)."""

    def __init__(self, *, read_service_factory: Callable[[], Any], session_mapper: Any) -> None:
        self._read_service_factory = read_service_factory
        self._session_mapper = session_mapper

    async def resolve(self, intent: OutreachIntent) -> ResolvedTargets:
        session_id = intent.origin_session_id
        if not session_id:
            return ResolvedTargets()

        desktop_session_id: str | None = None
        try:
            summary = await self._read_service_factory().aget_session_summary(
                intent.user_id, session_id
            )
            if summary is not None:
                desktop_session_id = session_id
        except Exception:
            logger.warning("outreach: session validity check failed", exc_info=True)
            raise

        if desktop_session_id is None:
            return ResolvedTargets()

        external: ChannelTarget | None = None
        try:
            mapping = await self._session_mapper.lookup_by_session(session_id)
        except Exception:
            logger.warning("outreach: session mapping lookup failed", exc_info=True)
            raise
        if mapping is not None and getattr(mapping, "channel_type", None) and mapping.channel_type != "chat_sse":
            external = ChannelTarget(
                channel_type=mapping.channel_type,
                # Leave empty: external channels resolve their chat_id from
                # magi_session_id via session_mapper at deliver time (matches the
                # proven interactive-reply path in channels/delivery_prefs.py).
                external_chat_id="",
                magi_session_id=session_id,
                magi_user_id=intent.user_id,
            )

        return ResolvedTargets(desktop_session_id=desktop_session_id, external=external)
