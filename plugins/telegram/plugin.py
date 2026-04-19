"""Telegram channel plugin — wraps the Telegram channel adapter as a plugin contribution."""

from __future__ import annotations

from typing import Any

from magi.channels.base import Channel
from magi.channels.telegram.adapter import TelegramChannel, TelegramChannelConfig
from magi.plugins.base import Plugin
from magi.plugins.contracts import ExtensionFieldOption, ExtensionFieldSpec


class TelegramPlugin(Plugin):
    """Telegram bot channel plugin.

    Exposes a bidirectional Telegram bot as a channel contribution.
    Configure bot_token and other settings through the Extensions settings panel.
    """

    def get_channel(self) -> Channel:
        config = TelegramChannelConfig(
            bot_token=self.settings.get("bot_token", ""),
            mode=self.settings.get("mode", "polling"),
            webhook_url=self.settings.get("webhook_url", ""),
            webhook_secret=self.settings.get("webhook_secret", ""),
            proxy=self.settings.get("proxy", ""),
            allowed_user_ids=list(self.settings.get("allowed_user_ids") or []),
            group_trigger_keyword=self.settings.get("group_trigger_keyword", ""),
            magi_user_id=self.settings.get("magi_user_id", "default"),
            max_message_length=int(self.settings.get("max_message_length", 4096)),
        )
        return TelegramChannel(config=config)

    def get_channel_fields(self) -> list[ExtensionFieldSpec]:
        return [
            ExtensionFieldSpec(
                key="bot_token",
                type="secret",
                label="Bot Token",
                description="Telegram bot token from @BotFather.",
                required=True,
                surface="extensions",
                order=0,
            ),
            ExtensionFieldSpec(
                key="mode",
                type="select",
                label="Connection Mode",
                description="Polling checks for updates periodically; Webhook requires a public HTTPS URL.",
                default="polling",
                options=[
                    ExtensionFieldOption(label="Polling", value="polling"),
                    ExtensionFieldOption(label="Webhook", value="webhook"),
                ],
                surface="extensions",
                order=1,
            ),
            ExtensionFieldSpec(
                key="webhook_url",
                type="input",
                label="Webhook URL",
                description="Public HTTPS URL for webhook mode. Required when mode is 'webhook'.",
                default="",
                placeholder="https://your-domain.com/webhook/telegram",
                depends_on_key="mode",
                depends_on_values=["webhook"],
                surface="extensions",
                order=2,
            ),
            ExtensionFieldSpec(
                key="proxy",
                type="input",
                label="Proxy",
                description="HTTP/SOCKS5 proxy URL. Leave empty to use the global network proxy.",
                default="",
                placeholder="http://127.0.0.1:7890",
                surface="extensions",
                order=3,
            ),
            ExtensionFieldSpec(
                key="allowed_user_ids",
                type="tags",
                label="Allowed User IDs",
                description="Whitelist of Telegram user IDs. Empty means allow all users.",
                default=[],
                surface="extensions",
                order=4,
            ),
            ExtensionFieldSpec(
                key="group_trigger_keyword",
                type="input",
                label="Group Trigger Keyword",
                description="Keyword prefix that triggers the bot in group chats.",
                default="",
                placeholder="magi",
                surface="extensions",
                order=5,
            ),
            ExtensionFieldSpec(
                key="magi_user_id",
                type="input",
                label="Magi User ID",
                description="Magi user identity to associate with this channel.",
                default="default",
                surface="extensions",
                order=6,
            ),
            ExtensionFieldSpec(
                key="max_message_length",
                type="number",
                label="Max Message Length",
                description="Maximum characters per Telegram message (1–4096).",
                default=4096,
                surface="extensions",
                order=7,
            ),
        ]
