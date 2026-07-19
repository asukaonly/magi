"""Strict validation before chat messages claim managed asset ownership."""

from __future__ import annotations

import hashlib
import os
from typing import BinaryIO

from ..utils.runtime import RuntimePaths
from magi.core.chat_assets.io import (
    open_managed_chat_attachment,
    open_managed_chat_derived_file,
)
from magi.core.chat_assets.paths import is_safe_chat_asset_component


class ChatAssetOwnershipError(ValueError):
    """Raised when a message cannot safely claim all referenced asset files."""


def has_managed_asset_payloads(value: object) -> bool:
    """Return whether a payload list can add managed filesystem ownership."""

    if not isinstance(value, list):
        return False
    return any(
        isinstance(item, dict) and str(item.get("kind") or "").strip() != "mcp_resource"
        for item in value
    )


def has_explicit_asset_payloads(value: object) -> bool:
    """Return whether a caller explicitly requested attachment replacement."""

    return value is not None


def has_explicit_asset_payload_map(value: object) -> bool:
    """Return whether a message map contains any explicit replacement list."""

    if not isinstance(value, dict):
        return False
    return any(item is not None for item in value.values())


def validate_message_asset_payloads(
    attachment_payloads: list[dict[str, object]] | None,
    *,
    session_id: str,
    turn_id: str | None,
    runtime_paths: RuntimePaths,
) -> None:
    """Require every managed attachment reference to be complete and exact."""

    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    for attachment in attachment_payloads or []:
        if not isinstance(attachment, dict):
            raise ChatAssetOwnershipError("Attachment metadata must be an object")
        if str(attachment.get("kind") or "").strip() == "mcp_resource":
            continue
        attachment_id = str(attachment.get("attachment_id") or "").strip()
        if (
            not is_safe_chat_asset_component(normalized_session_id)
            or not is_safe_chat_asset_component(normalized_turn_id)
            or not is_safe_chat_asset_component(attachment_id)
        ):
            raise ChatAssetOwnershipError(
                "Managed attachment identity does not match a valid chat turn"
            )
        _require_payload_scope(
            attachment,
            field="session_id",
            expected=normalized_session_id,
        )
        _require_payload_scope(
            attachment,
            field="turn_id",
            expected=normalized_turn_id,
        )
        source_handle = open_managed_chat_attachment(
            attachment.get("storage_path"),
            session_id=normalized_session_id,
            turn_id=normalized_turn_id,
            attachment_id=attachment_id,
            original_name=attachment.get("original_name"),
            runtime_paths=runtime_paths,
        )
        if source_handle is None:
            raise ChatAssetOwnershipError(
                "Managed attachment file is missing or outside its exact chat turn"
            )
        with source_handle:
            source_stat = os.fstat(source_handle.fileno())
            _require_expected_size(attachment, source_stat.st_size)
            _require_expected_sha256(attachment, source_handle, source_stat)

        raw_derived_path = str(attachment.get("derived_text_path") or "").strip()
        if raw_derived_path:
            derived_handle = open_managed_chat_derived_file(
                raw_derived_path,
                session_id=normalized_session_id,
                turn_id=normalized_turn_id,
                attachment_id=attachment_id,
                runtime_paths=runtime_paths,
            )
            if derived_handle is None:
                raise ChatAssetOwnershipError(
                    "Managed derived attachment file is missing or outside its exact chat turn"
                )
            derived_handle.close()


def _require_payload_scope(
    attachment: dict[str, object],
    *,
    field: str,
    expected: str,
) -> None:
    supplied = str(attachment.get(field) or "").strip()
    if supplied and supplied != expected:
        raise ChatAssetOwnershipError(f"Managed attachment {field} does not match its message")


def _require_expected_size(
    attachment: dict[str, object],
    actual_size: int,
) -> None:
    if "size_bytes" not in attachment or attachment.get("size_bytes") is None:
        return
    raw_size = attachment.get("size_bytes")
    if isinstance(raw_size, bool):
        raise ChatAssetOwnershipError("Managed attachment size is invalid")
    try:
        expected_size = int(str(raw_size))
    except (TypeError, ValueError) as exc:
        raise ChatAssetOwnershipError("Managed attachment size is invalid") from exc
    if expected_size != int(actual_size):
        raise ChatAssetOwnershipError("Managed attachment size changed before persistence")


def _require_expected_sha256(
    attachment: dict[str, object],
    handle: BinaryIO,
    initial_stat: os.stat_result,
) -> None:
    expected_sha256 = str(attachment.get("sha256") or "").strip().lower()
    if not expected_sha256:
        return
    digest = hashlib.sha256()
    try:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
        final_stat = os.fstat(handle.fileno())
    except OSError as exc:
        raise ChatAssetOwnershipError("Managed attachment file changed during validation") from exc
    initial_identity = (
        initial_stat.st_dev,
        initial_stat.st_ino,
        initial_stat.st_size,
        initial_stat.st_mtime_ns,
    )
    final_identity = (
        final_stat.st_dev,
        final_stat.st_ino,
        final_stat.st_size,
        final_stat.st_mtime_ns,
    )
    if initial_identity != final_identity:
        raise ChatAssetOwnershipError("Managed attachment file changed during validation")
    if digest.hexdigest() != expected_sha256:
        raise ChatAssetOwnershipError("Managed attachment checksum changed before persistence")


__all__ = [
    "ChatAssetOwnershipError",
    "has_explicit_asset_payload_map",
    "has_explicit_asset_payloads",
    "has_managed_asset_payloads",
    "validate_message_asset_payloads",
]
