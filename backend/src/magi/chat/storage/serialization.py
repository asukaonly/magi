"""Pure serialization helpers for chat store records."""

from __future__ import annotations

from .relational import ChatRow

import json
from pathlib import Path
from typing import Literal


from ...utils.runtime import RuntimePaths, get_runtime_paths
from magi.core.chat_assets.paths import (
    build_chat_derived_path,
    is_safe_chat_asset_component,
    resolve_chat_attachment_file,
    resolve_chat_derived_file,
    verified_chat_resources_dir,
)
from ..contracts import ChatMessageLabel, ChatMessageRecord

ChatAssetKind = Literal["attachment", "derived_text"]




def managed_chat_asset_reference(
    storage_path: object,
    *,
    runtime_paths: RuntimePaths | None = None,
) -> tuple[str, str] | None:
    """Return the canonical key and base-relative path for one chat asset."""
    normalized = str(storage_path or "").strip()
    if not normalized:
        return None
    paths = runtime_paths or get_runtime_paths()
    base_dir = paths.base_dir.resolve()
    try:
        resources_dir = verified_chat_resources_dir(paths)
    except ValueError:
        return None
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    try:
        parent = candidate.parent.resolve()
        parent.relative_to(resources_dir)
        target = parent / candidate.name
        if target.is_symlink():
            return None
        asset_key = target.relative_to(resources_dir).as_posix()
        relative_path = target.relative_to(base_dir).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None
    return asset_key, relative_path


def message_attachment_storage_reference(
    storage_path: object,
    *,
    session_id: object,
    turn_id: object,
    attachment_id: object,
    runtime_paths: RuntimePaths | None = None,
) -> tuple[str, str] | None:
    """Resolve one original attachment inside its owning message turn."""

    paths = runtime_paths or get_runtime_paths()
    resolved = resolve_chat_attachment_file(
        storage_path,
        session_id=session_id,
        turn_id=turn_id,
        attachment_id=attachment_id,
        runtime_paths=paths,
    )
    if resolved is None:
        return None
    return managed_chat_asset_reference(resolved, runtime_paths=paths)


def message_asset_references(
    attachment_payloads: list[dict[str, object]] | None,
    *,
    session_id: str,
    turn_id: str | None,
    runtime_paths: RuntimePaths | None = None,
) -> tuple[tuple[str, str, ChatAssetKind], ...]:
    """Resolve every original and derived file owned by one message."""
    unique: dict[str, tuple[str, ChatAssetKind]] = {}
    paths = runtime_paths or get_runtime_paths()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    for attachment in attachment_payloads or []:
        if not isinstance(attachment, dict):
            continue
        attachment_id = str(attachment.get("attachment_id") or "").strip()
        if (
            not is_safe_chat_asset_component(attachment_id)
            or not is_safe_chat_asset_component(normalized_session_id)
            or not is_safe_chat_asset_component(normalized_turn_id)
        ):
            continue
        original_reference = message_attachment_storage_reference(
            attachment.get("storage_path"),
            session_id=normalized_session_id,
            turn_id=normalized_turn_id,
            attachment_id=attachment_id,
            runtime_paths=paths,
        )
        if original_reference is not None:
            asset_key, relative_path = original_reference
            unique.setdefault(asset_key, (relative_path, "attachment"))
        derived_path = resolve_chat_derived_file(
            attachment.get("derived_text_path"),
            session_id=normalized_session_id,
            turn_id=normalized_turn_id,
            attachment_id=attachment_id,
            runtime_paths=paths,
        )
        if derived_path is not None:
            reference = managed_chat_asset_reference(
                derived_path,
                runtime_paths=paths,
            )
            if reference is not None:
                asset_key, relative_path = reference
                unique.setdefault(asset_key, (relative_path, "derived_text"))
        inferred_path = build_chat_derived_path(
            session_id=normalized_session_id,
            turn_id=normalized_turn_id,
            attachment_id=attachment_id,
            runtime_paths=paths,
        )
        inferred_reference = managed_chat_asset_reference(
            inferred_path,
            runtime_paths=paths,
        )
        if inferred_reference is not None:
            asset_key, relative_path = inferred_reference
            unique.setdefault(asset_key, (relative_path, "derived_text"))
    return tuple(
        (asset_key, relative_path, asset_kind)
        for asset_key, (relative_path, asset_kind) in unique.items()
    )

from magi_plugin_sdk.storage_chat.serialization import (
    _coerce_int,
    row_to_message,
    normalize_message_label,
    serialize_message_label,
    parse_message_label,
)
