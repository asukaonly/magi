"""Domain-owned persistence contracts for channel bindings."""

from __future__ import annotations

from dataclasses import dataclass
from magi_plugin_sdk.delivery import DeliveryReceipt
from typing import Protocol
from .contracts import ChannelSessionMapping, ChannelBindingSettings


class ChannelSessionRepository(Protocol):
    """Persist bindings without exposing a driver, connection, or path."""

    async def initialize(self) -> None: ...

    async def lookup(
        self, channel_type: str, external_chat_id: str, *, external_thread_id: str | None = None
    ) -> ChannelSessionMapping | None: ...

    async def list_all(self) -> list[ChannelSessionMapping]: ...

    async def lookup_by_session(self, magi_session_id: str) -> ChannelSessionMapping | None: ...

    async def delete_mapping(
        self, channel_type: str, external_chat_id: str, *, external_thread_id: str | None = None
    ) -> None: ...

    async def clear_conversation_state(self) -> dict[str, int]: ...

    async def get_notification_cursor(self, channel_type: str, external_chat_id: str) -> int: ...

    async def update_notification_cursor(
        self, channel_type: str, external_chat_id: str, notification_id: int
    ) -> None: ...

    async def get_relay_cursor(self, state_key: str) -> int: ...

    async def update_relay_cursor(self, state_key: str, notification_id: int) -> None: ...

    async def insert(self, mapping: ChannelSessionMapping) -> None: ...

    async def touch(
        self,
        channel_type: str,
        external_chat_id: str,
        now_ms: int,
        *,
        external_thread_id: str | None = None,
    ) -> None: ...


class DeliveryReceiptsRepository(Protocol):
    async def initialize(self) -> None: ...
    async def save_receipts(
        self, *, session_id: str, run_id: str, revision: int, receipts: list[DeliveryReceipt]
    ) -> None: ...
    async def list_receipts(
        self, *, session_id: str, run_id: str, revision: int | None = None
    ) -> list[DeliveryReceipt]: ...
    async def clear_receipts(self, *, session_id: str, run_id: str) -> None: ...


class ChannelBindingSettingsRepository(Protocol):
    async def initialize(self) -> None: ...
    async def get(self, *, channel_type: str, external_user_id: str) -> ChannelBindingSettings: ...
    async def set_auto_approve(
        self, *, channel_type: str, external_user_id: str, auto_approve: bool
    ) -> ChannelBindingSettings: ...
    async def list_all(self) -> list[ChannelBindingSettings]: ...


@dataclass(frozen=True)
class ChannelRepositories:
    sessions: ChannelSessionRepository
    receipts: DeliveryReceiptsRepository
    binding_settings: ChannelBindingSettingsRepository
