"""Telegram channel adapter — python-telegram-bot based implementation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ...core.logger import get_logger
from ..base import Channel
from ..contracts import ChannelTarget, InboundMessage, OutboundContent
from ..session_mapper import ChannelSessionMapper
from .formatter import telegram_format

logger = get_logger(__name__)


@dataclass
class TelegramChannelConfig:
    """Telegram-specific channel configuration."""

    bot_token: str = ""
    mode: str = "polling"  # "polling" | "webhook"
    webhook_url: str = ""
    webhook_secret: str = ""
    allowed_user_ids: list[str] = field(default_factory=list)
    group_trigger_keyword: str = ""
    magi_user_id: str = "default"
    max_message_length: int = 4096


class TelegramChannel(Channel):
    """Bidirectional Telegram bot channel."""

    def __init__(
        self,
        *,
        config: TelegramChannelConfig,
        session_mapper: ChannelSessionMapper,
    ) -> None:
        self._config = config
        self._session_mapper = session_mapper
        self._application: Any = None
        self._bot_username: str = ""
        self._bot_id: int = 0

    @property
    def channel_type(self) -> str:
        return "telegram"

    async def start(self) -> None:
        try:
            from telegram.ext import (
                Application,
                CommandHandler,
                MessageHandler,
                filters,
            )
        except ImportError:
            raise RuntimeError(
                "python-telegram-bot is not installed. "
                "Install with: pip install 'python-telegram-bot>=22.0'"
            )

        if not self._config.bot_token:
            raise ValueError("Telegram bot token is required")

        self._application = (
            Application.builder().token(self._config.bot_token).build()
        )

        self._application.add_handler(CommandHandler("start", self._on_start_command))
        self._application.add_handler(CommandHandler("reset", self._on_reset_command))
        self._application.add_handler(CommandHandler("ask", self._on_ask_command))
        self._application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )

        await self._application.initialize()
        bot_info = await self._application.bot.get_me()
        self._bot_username = bot_info.username or ""
        self._bot_id = bot_info.id
        logger.info(
            "Telegram bot initialized",
            username=self._bot_username,
            bot_id=self._bot_id,
        )

        if self._config.mode == "webhook" and self._config.webhook_url:
            await self._application.bot.set_webhook(
                url=self._config.webhook_url,
                secret_token=self._config.webhook_secret or None,
            )
            await self._application.start()
            logger.info("Telegram channel started in webhook mode")
        else:
            await self._application.start()
            await self._application.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram channel started in polling mode")

    async def stop(self) -> None:
        if self._application is None:
            return
        try:
            if self._application.updater and self._application.updater.running:
                await self._application.updater.stop()
            await self._application.stop()
            await self._application.shutdown()
        except Exception:
            logger.exception("Error stopping Telegram channel")
        self._application = None

    async def send_message(self, target: ChannelTarget, content: OutboundContent) -> None:
        if self._application is None:
            return
        text = telegram_format(content.text, max_length=self._config.max_message_length)
        if not text.strip():
            return
        kwargs: dict[str, Any] = {
            "chat_id": int(target.external_chat_id),
            "text": text,
        }
        # Try MarkdownV2 first; fall back to plain text on parse error.
        try:
            await self._application.bot.send_message(parse_mode="MarkdownV2", **kwargs)
        except Exception:
            logger.debug("MarkdownV2 send failed, retrying as plain text")
            kwargs["text"] = content.text[: self._config.max_message_length]
            try:
                await self._application.bot.send_message(**kwargs)
            except Exception:
                logger.exception(
                    "Failed to send message to Telegram",
                    chat_id=target.external_chat_id,
                )

    async def send_typing_indicator(self, target: ChannelTarget) -> None:
        if self._application is None:
            return
        try:
            await self._application.bot.send_chat_action(
                chat_id=int(target.external_chat_id), action="typing"
            )
        except Exception:
            pass  # Non-critical

    # -- Telegram handlers ----------------------------------------------------

    async def _on_start_command(self, update: Any, context: Any) -> None:
        chat = update.effective_chat
        if chat is None:
            return
        await context.bot.send_message(
            chat_id=chat.id,
            text="Hello! I'm your Magi assistant. Send me a message to get started.",
        )

    async def _on_reset_command(self, update: Any, context: Any) -> None:
        chat = update.effective_chat
        user = update.effective_user
        if chat is None or user is None:
            return
        external_chat_id = str(chat.id)
        await self._session_mapper.delete_mapping("telegram", external_chat_id)
        await context.bot.send_message(
            chat_id=chat.id,
            text="Session reset. Your next message will start a new conversation.",
        )

    async def _on_ask_command(self, update: Any, context: Any) -> None:
        """Handle /ask <message> in group or DM."""
        message = update.effective_message
        if message is None or not message.text:
            return
        text = message.text.lstrip("/ask").strip()
        if not text:
            return
        await self._process_inbound(update, text)

    async def _on_message(self, update: Any, context: Any) -> None:
        message = update.effective_message
        if message is None or not message.text:
            return
        chat = update.effective_chat
        if chat is None:
            return

        is_group = chat.type in ("group", "supergroup")
        if is_group:
            if not self._should_process_group(message):
                return
            text = self._strip_mention(message.text)
        else:
            text = message.text

        await self._process_inbound(update, text)

    async def _process_inbound(self, update: Any, text: str) -> None:
        """Common inbound processing for all entry points."""
        message = update.effective_message
        chat = update.effective_chat
        user = update.effective_user
        if message is None or chat is None or user is None:
            return

        external_user_id = str(user.id)
        if not self._is_user_allowed(external_user_id):
            return

        is_group = chat.type in ("group", "supergroup")
        display_name = self._build_display_name(chat, user, is_group)

        mapping = await self._session_mapper.resolve_or_create(
            channel_type="telegram",
            external_chat_id=str(chat.id),
            external_user_id=external_user_id,
            is_group=is_group,
            display_name=display_name,
        )

        # Show typing indicator
        try:
            await self._application.bot.send_chat_action(
                chat_id=chat.id, action="typing"
            )
        except Exception:
            pass

        # Dispatch through standard Magi pipeline
        from ...api.services.message_dispatch_service import dispatch_user_message

        metadata = {
            "channel_type": "telegram",
            "external_chat_id": str(chat.id),
            "external_user_id": external_user_id,
            "external_message_id": str(message.message_id),
            "external_username": user.username,
            "is_group": is_group,
        }

        outcome = await dispatch_user_message(
            source="telegram",
            user_id=mapping.magi_user_id,
            session_id=mapping.magi_session_id,
            message=text.strip(),
            metadata=metadata,
        )

        if not outcome.success:
            logger.warning(
                "Telegram dispatch failed",
                error_code=outcome.error_code,
                error_message=outcome.error_message,
            )

    # -- Helpers --------------------------------------------------------------

    def _should_process_group(self, message: Any) -> bool:
        """Check if a group message should trigger the bot."""
        text = message.text or ""

        # @mention check
        if message.entities:
            for entity in message.entities:
                if entity.type == "mention":
                    mention_text = text[entity.offset : entity.offset + entity.length]
                    if mention_text.lower() == f"@{self._bot_username.lower()}":
                        return True
                elif entity.type == "text_mention" and entity.user:
                    if entity.user.id == self._bot_id:
                        return True

        # Reply to bot message
        if message.reply_to_message and message.reply_to_message.from_user:
            if message.reply_to_message.from_user.id == self._bot_id:
                return True

        # Keyword trigger
        keyword = self._config.group_trigger_keyword
        if keyword and text.startswith(keyword):
            return True

        return False

    def _strip_mention(self, text: str) -> str:
        """Remove @bot_username from text."""
        if not self._bot_username:
            return text
        return text.replace(f"@{self._bot_username}", "").strip()

    def _is_user_allowed(self, external_user_id: str) -> bool:
        """Check user against whitelist (empty = allow all)."""
        if not self._config.allowed_user_ids:
            return True
        return external_user_id in self._config.allowed_user_ids

    @staticmethod
    def _build_display_name(chat: Any, user: Any, is_group: bool) -> str:
        if is_group:
            return f"TG Group: {chat.title or chat.id}"
        name_parts = [user.first_name or "", user.last_name or ""]
        full_name = " ".join(p for p in name_parts if p).strip()
        if user.username:
            return f"TG: @{user.username}" + (f" ({full_name})" if full_name else "")
        return f"TG: {full_name or user.id}"
