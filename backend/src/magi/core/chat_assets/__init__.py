"""Low-level primitives for managed chat assets."""

from .io import (
    CHAT_ASSET_READ_CHUNK_BYTES,
    aopen_managed_chat_attachment,
    open_managed_chat_attachment,
    open_managed_chat_derived_file,
    stream_managed_chat_file,
    write_managed_chat_asset_atomically,
)
from .mutations import (
    chat_asset_mutation,
    chat_asset_mutation_guarded_if,
    chat_asset_mutation_is_held,
    require_chat_asset_mutation,
    run_chat_asset_mutation,
)
from .paths import (
    SAFE_CHAT_ASSET_COMPONENT_PATTERN,
    asset_scope_identity_key,
    build_chat_derived_path,
    is_safe_chat_asset_component,
    normalize_chat_asset_component,
    prepare_chat_asset_turn_directory,
    prepare_chat_derived_write_path,
    resolve_chat_asset_session_directory,
    resolve_chat_asset_turn_directory,
    resolve_chat_attachment_file,
    resolve_chat_derived_file,
    verified_chat_asset_root,
    verified_chat_resources_dir,
)

__all__ = [
    "CHAT_ASSET_READ_CHUNK_BYTES",
    "SAFE_CHAT_ASSET_COMPONENT_PATTERN",
    "aopen_managed_chat_attachment",
    "asset_scope_identity_key",
    "build_chat_derived_path",
    "chat_asset_mutation",
    "chat_asset_mutation_guarded_if",
    "chat_asset_mutation_is_held",
    "is_safe_chat_asset_component",
    "normalize_chat_asset_component",
    "open_managed_chat_attachment",
    "open_managed_chat_derived_file",
    "prepare_chat_asset_turn_directory",
    "prepare_chat_derived_write_path",
    "require_chat_asset_mutation",
    "resolve_chat_asset_session_directory",
    "resolve_chat_asset_turn_directory",
    "resolve_chat_attachment_file",
    "resolve_chat_derived_file",
    "run_chat_asset_mutation",
    "stream_managed_chat_file",
    "verified_chat_asset_root",
    "verified_chat_resources_dir",
    "write_managed_chat_asset_atomically",
]
