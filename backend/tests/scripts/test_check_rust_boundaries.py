"""Regression checks for desktop/service compilation boundaries."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "check_rust_boundaries", ROOT / "scripts/check-rust-boundaries.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def metadata_with_dependency(owner: str, dependency_name: str, **options):
    packages = [
        {"id": name, "name": name, "dependencies": []} for name in MODULE.WORKSPACE_DEPENDENCIES
    ]
    next(package for package in packages if package["name"] == owner)["dependencies"].append(
        {"name": dependency_name, **options}
    )
    return {"workspace_members": list(MODULE.WORKSPACE_DEPENDENCIES), "packages": packages}


@pytest.mark.parametrize("kind", [None, "build", "dev"])
@pytest.mark.parametrize("target", ["magi-server-runtime", "magi-gateway", "rusqlite", "axum"])
def test_desktop_cannot_import_service_implementation_even_with_aliases_or_target_gates(
    kind, target
):
    metadata = metadata_with_dependency(
        "magi-desktop", target, kind=kind, rename="helper", target="cfg(windows)", optional=True
    )
    assert MODULE.validate_metadata(metadata)


@pytest.mark.parametrize("owner", ["magi-server", "magi-server-runtime", "magi-gateway"])
def test_service_cannot_import_desktop(owner):
    assert MODULE.validate_metadata(metadata_with_dependency(owner, "tauri"))


@pytest.mark.parametrize(
    "owner,target",
    [
        ("magi-service-contract", "tokio"),
        ("magi-platform", "serde_json"),
        ("magi-service-contract", "magi-gateway"),
    ],
)
def test_shared_crates_cannot_hide_implementation_dependencies(owner, target):
    assert MODULE.validate_metadata(metadata_with_dependency(owner, target))


def test_cli_gateway_dependency_is_only_allowed_for_tests():
    assert MODULE.validate_metadata(metadata_with_dependency("magi-server", "magi-gateway"))
    assert not MODULE.validate_metadata(
        metadata_with_dependency("magi-server", "magi-gateway", kind="dev")
    )


def test_unknown_local_bridge_requires_review():
    assert MODULE.validate_metadata(
        metadata_with_dependency("magi-desktop", "helper", path="/tmp/helper")
    )


def test_desktop_can_share_launch_contract_without_service_runtime():
    assert not MODULE.validate_metadata(
        metadata_with_dependency("magi-desktop", "magi-service-contract")
    )
