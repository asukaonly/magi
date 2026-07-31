"""Canonical plugin package version parsing and comparison."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import StringConstraints

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


__all__ = [
    "MAX_PLUGIN_VERSION_LENGTH",
    "PLUGIN_VERSION_PATTERN",
    "PluginVersion",
    "is_plugin_version_newer",
    "parse_plugin_version",
]
