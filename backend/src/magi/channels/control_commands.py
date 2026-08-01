"""Unified host control-command port — permission + session + help.

Single entry point for ALL channel control commands. A channel calls
``handle_command`` for an inbound message BEFORE dispatching it as chat; a
non-``None`` :class:`ChannelControlCommandResult` means the message was a
control command (surface ``result.ack`` and stop), ``None`` means dispatch
normally.

This composes the EXISTING per-domain parsers behind one typed result rather
than rewriting them:
- permission (``/approve|/deny`` + 同意/拒绝 NL) → ``control.permission.slash_commands``
- session (``/new|/reset|/新会话|/重置`` + 整句) → ``channels.session_commands``
- ``/help`` → built here.

So the reset/mapping chain stays single (session_commands) and the shipped
permission resolution is untouched (just invoked from one more place), while
plugins get a clean typed contract instead of overloading the dispatch
outcome's ``error_message``.
"""
from __future__ import annotations

from typing import Any

from magi_plugin_sdk.channels import (
    ChannelControlCommandResult,
    ChannelInboundContext,
)

from ..core.logger import get_logger
from .ingress_boundary import ChannelIngressBoundary

logger = get_logger(__name__)

#: One-line help per command family. Hardcoded Chinese, consistent with the
#: existing slash-command acks (migrate to i18n together if/when those are).
_HELP_LINES = (
    "/new、/reset、/新会话、/重置 —— 开启全新会话(旧历史保留、不带入)",
    "/approve、/deny —— 同意 / 拒绝当前待审批的工具请求",
    "/help —— 显示这份命令列表",
)

_HELP_TRIGGERS = frozenset({"/help", "/?", "help", "帮助", "命令"})


def _is_help_command(message: str) -> bool:
    return (message or "").strip().lower() in _HELP_TRIGGERS


def _help_ack() -> str:
    return "可用命令:\n" + "\n".join(_HELP_LINES)


class HostControlPort:
    """Implements ``ChannelControlPortProtocol`` by composing existing parsers.

    Deps (any may be ``None`` in degraded/test setups — the matching family is
    then skipped): ``session_mapper`` (session reset), ``permission_registry`` +
    ``interaction_broker`` (permission approve/deny).
    """

    def __init__(
        self,
        *,
        ingress_boundary: ChannelIngressBoundary,
        session_mapper: Any = None,
        permission_registry: Any = None,
        interaction_broker: Any = None,
    ) -> None:
        self._ingress_boundary = ingress_boundary
        self._session_mapper = session_mapper
        self._permission_registry = permission_registry
        self._broker = interaction_broker

    async def handle_command(
        self,
        *,
        inbound_context: ChannelInboundContext,
        message: str,
        session_id: str | None,
        channel_type: str,
        external_chat_id: str,
        external_user_id: str,
    ) -> ChannelControlCommandResult | None:
        async with self._ingress_boundary.operation(
            inbound_context,
            expected_channel_type=channel_type,
        ):
            return await self._handle_admitted_command(
                message=message,
                session_id=session_id,
                channel_type=channel_type,
                external_chat_id=external_chat_id,
                external_user_id=external_user_id,
            )

    async def _handle_admitted_command(
        self,
        *,
        message: str,
        session_id: str | None,
        channel_type: str,
        external_chat_id: str,
        external_user_id: str,
    ) -> ChannelControlCommandResult | None:
        _ = channel_type, external_chat_id, external_user_id  # reserved for future commands

        # 1) Permission (/approve|/deny + gated NL). Verbs are disjoint from
        #    session verbs, so order is safe.
        if self._permission_registry is not None and self._broker is not None:
            try:
                from ..control.permission.slash_commands import try_handle_control_command

                perm = await try_handle_control_command(
                    message=message,
                    session_id=session_id,
                    registry=self._permission_registry,
                    broker=self._broker,
                )
                if perm.handled:
                    return ChannelControlCommandResult(ack=perm.ack_message, kind="permission")
            except Exception:  # noqa: BLE001 — a control parser must never break dispatch
                logger.debug("control_command.permission_failed", exc_info=True)

        # 2) Session (/new|/reset|/新会话|/重置 + exact phrases) — the ONE reset chain.
        if self._session_mapper is not None:
            try:
                from .session_commands import try_handle_session_command

                sess = await try_handle_session_command(
                    message=message,
                    session_id=session_id,
                    session_mapper=self._session_mapper,
                )
                if sess.handled:
                    return ChannelControlCommandResult(ack=sess.ack_message, kind="session")
            except Exception:  # noqa: BLE001
                logger.debug("control_command.session_failed", exc_info=True)

        # 3) Help.
        if _is_help_command(message):
            return ChannelControlCommandResult(ack=_help_ack(), kind="help")

        return None


__all__ = ["HostControlPort"]
