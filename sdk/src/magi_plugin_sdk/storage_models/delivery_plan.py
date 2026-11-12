"""Shared chat persistence contracts and value codecs."""

from dataclasses import dataclass
from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.endpoints import EndpointRef


@dataclass(frozen=True, slots=True)
class DeliveryPlan:
    """A fixed destination snapshot; retries must reuse this value."""

    session_id: str
    user_id: str
    targets: tuple[EndpointRef, ...]

    def channel_targets(self) -> list[ChannelTarget]:
        return [ChannelTarget(
            channel_type=target.registry_key,
            external_chat_id="" if target.registry_key == "chat_sse" else target.target_id,
            external_thread_id=target.thread_id,
            magi_session_id=self.session_id,
            magi_user_id=self.user_id,
        ) for target in self.targets]
