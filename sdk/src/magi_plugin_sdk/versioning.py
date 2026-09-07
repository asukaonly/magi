"""Canonical versions and shared plugin runtime admission rules."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import StringConstraints

PLUGIN_PROTOCOL_VERSION = 2
MAX_PLUGIN_VERSION_LENGTH = 32
PLUGIN_VERSION_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
_PLUGIN_VERSION_PATTERN = re.compile(PLUGIN_VERSION_PATTERN)
PluginVersion = Annotated[
    str,
    StringConstraints(
        max_length=MAX_PLUGIN_VERSION_LENGTH,
        pattern=PLUGIN_VERSION_PATTERN,
    ),
]


def parse_plugin_version(value: str) -> tuple[int, int, int]:
    """Parse the canonical MAJOR.MINOR.PATCH plugin version contract."""

    if not isinstance(value, str) or len(value) > MAX_PLUGIN_VERSION_LENGTH:
        raise ValueError("Plugin version must be a MAJOR.MINOR.PATCH string")
    match = _PLUGIN_VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("Plugin version must use canonical MAJOR.MINOR.PATCH form")
    return tuple(int(part) for part in match.groups())


def is_plugin_version_newer(remote: str, local: str) -> bool:
    """Return whether one canonical plugin version is strictly newer."""

    return parse_plugin_version(remote) > parse_plugin_version(local)


def validate_sdk_requirement(
    min_sdk_version: str,
    *,
    protocol_version: int,
    sdk_version: str,
) -> None:
    """Require protocol 2 and an SDK at least as new as the declared minimum.

    Hosts and workers pass their actual SDK version explicitly. This checks
    package admission; handshake peers must still agree on the exact SDK
    version before loading plugin code.

    Raises:
        ValueError: The protocol is unsupported, a version is malformed, or
            the running SDK is older than the declared minimum.
    """
    if type(protocol_version) is not int or protocol_version != PLUGIN_PROTOCOL_VERSION:
        raise ValueError(f"Unsupported plugin protocol: {protocol_version}")
    minimum = parse_plugin_version(min_sdk_version)
    actual = parse_plugin_version(sdk_version)
    if actual < minimum:
        raise ValueError(f"Plugin requires SDK {min_sdk_version}; runtime SDK is {sdk_version}")


__all__ = [
    "PLUGIN_PROTOCOL_VERSION",
    "MAX_PLUGIN_VERSION_LENGTH",
    "PLUGIN_VERSION_PATTERN",
    "PluginVersion",
    "is_plugin_version_newer",
    "parse_plugin_version",
    "validate_sdk_requirement",
]
