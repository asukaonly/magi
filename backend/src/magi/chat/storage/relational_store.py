"""Compose shared chat transactions with host-owned asset validation."""

from magi_plugin_sdk.storage_chat.relational_store import RelationalChatRepository as SharedChatRepository

from ...core.chat_assets.mutations import chat_asset_mutation_guarded_if
from ...utils.runtime import RuntimePaths
from ..asset_validation import has_explicit_asset_payloads, has_explicit_asset_payload_map, has_managed_asset_payloads
from .host import LocalChatStorageHost
from .relational import ChatDatabase


class RelationalChatRepository(SharedChatRepository):
    def __init__(self, *, database: ChatDatabase, runtime_paths: RuntimePaths) -> None:
        super().__init__(database=database, host=LocalChatStorageHost(runtime_paths))

    append_message = chat_asset_mutation_guarded_if(
        "attachment_payloads", has_explicit_asset_payloads,
    )(SharedChatRepository.append_message)
    create_user_turn_once = chat_asset_mutation_guarded_if(
        "attachment_payloads", has_managed_asset_payloads,
    )(SharedChatRepository.create_user_turn_once)
    commit_user_turn_assistant_outcome = chat_asset_mutation_guarded_if(
        "attachment_payloads_by_message_id", has_explicit_asset_payload_map,
    )(SharedChatRepository.commit_user_turn_assistant_outcome)
    commit_unmanaged_assistant_outcome = chat_asset_mutation_guarded_if(
        "attachment_payloads_by_message_id", has_explicit_asset_payload_map,
    )(SharedChatRepository.commit_unmanaged_assistant_outcome)
