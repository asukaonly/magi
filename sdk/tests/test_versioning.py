from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from magi_plugin_sdk import (
    MAX_PLUGIN_VERSION_LENGTH,
    PLUGIN_VERSION_PATTERN,
    PluginVersion,
    is_plugin_version_newer,
    parse_plugin_version,
)


def test_plugin_version_contract_exports_are_stable() -> None:
    assert TypeAdapter(PluginVersion).validate_python("1.2.3") == "1.2.3"
    assert MAX_PLUGIN_VERSION_LENGTH == 32
    assert PLUGIN_VERSION_PATTERN == (
        r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
    )


@pytest.mark.parametrize(
    ("remote", "local", "expected"),
    [
        ("1.0.1", "1.0.0", True),
        ("1.1.0", "1.0.9", True),
        ("2.0.0", "1.99.99", True),
        ("1.0.0", "1.0.0", False),
        ("1.0.0", "1.0.1", False),
        ("1.9.9", "2.0.0", False),
    ],
)
def test_plugin_version_comparison_is_strict(
    remote: str,
    local: str,
    expected: bool,
) -> None:
    assert is_plugin_version_newer(remote, local) is expected


@pytest.mark.parametrize(
    "value",
    [
        "1",
        "1.0",
        "01.0.0",
        "1.0.0-beta",
        "1.0.0+build",
        "v1.0.0",
        "latest",
        f"{'1' * 33}.0.0",
    ],
)
def test_plugin_version_parser_rejects_noncanonical_values(value: str) -> None:
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        parse_plugin_version(value)
