"""Shared chat persistence contracts and value codecs."""

import re
import unicodedata


SAFE_CHAT_ASSET_COMPONENT_PATTERN = r"^[A-Za-z0-9_-]{1,128}$"


_SAFE_CHAT_ASSET_COMPONENT = re.compile(SAFE_CHAT_ASSET_COMPONENT_PATTERN)


def normalize_chat_asset_component(value: object, *, label: str) -> str:
    """Validate one identifier before using it as a filesystem component."""

    normalized = str(value or "").strip()
    if not _SAFE_CHAT_ASSET_COMPONENT.fullmatch(normalized):
        raise ValueError(
            f"{label} must contain only letters, numbers, underscores, or hyphens "
            "and be at most 128 characters"
        )
    return normalized


def is_safe_chat_asset_component(value: object) -> bool:
    """Return whether a value is safe as one managed asset path component."""

    return bool(_SAFE_CHAT_ASSET_COMPONENT.fullmatch(str(value or "").strip()))


def asset_scope_identity_key(value: object) -> str:
    """Return a conservative identity key for one filesystem path component."""

    return unicodedata.normalize("NFC", str(value or "")).casefold()
