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
from magi_plugin_sdk.versioning import validate_sdk_requirement


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


@pytest.mark.parametrize(
    ("minimum", "actual"),
    [
        ("0.2.0", "0.2.0"),
        ("0.2.0", "0.2.1"),
        ("0.2.1", "0.2.10"),
        ("0.1.9", "0.2.0"),
        ("0.2.99", "0.3.0"),
        ("0.99.99", "1.0.0"),
    ],
)
def test_sdk_requirement_accepts_minimum_or_newer_runtime(minimum: str, actual: str) -> None:
    assert validate_sdk_requirement(minimum, protocol_version=2, sdk_version=actual) is None


@pytest.mark.parametrize(
    ("minimum", "actual"),
    [("0.2.1", "0.2.0"), ("0.2.10", "0.2.9"), ("0.3.0", "0.2.99"), ("1.0.0", "0.99.99")],
)
def test_sdk_requirement_rejects_older_runtime(minimum: str, actual: str) -> None:
    with pytest.raises(ValueError, match=f"Plugin requires SDK {minimum}; runtime SDK is {actual}"):
        validate_sdk_requirement(minimum, protocol_version=2, sdk_version=actual)


@pytest.mark.parametrize("protocol", [1, 0, 3, -1, "2", 2.0, True, None])
def test_sdk_requirement_only_accepts_current_protocol(protocol) -> None:
    with pytest.raises(ValueError, match="Unsupported plugin protocol"):
        validate_sdk_requirement("0.1.0", protocol_version=protocol, sdk_version="0.2.1")


@pytest.mark.parametrize("value", ["", "latest", "0.2", "v0.2.0", "00.2.0", "0.2.0-rc.1", "0.2.0+build", "0.2.0\n", "1" * 33 + ".0.0", None, 2])
@pytest.mark.parametrize("field", ["min_sdk_version", "sdk_version"])
def test_sdk_requirement_validates_both_version_values(field, value) -> None:
    arguments = {"min_sdk_version": "0.2.0", "protocol_version": 2, "sdk_version": "0.2.1"}
    arguments[field] = value
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        validate_sdk_requirement(**arguments)
