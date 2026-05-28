"""AvailabilityResolver tests.

Covers: dispatch to check kinds, platform_support filtering, TTL cache,
manual invalidation, the no-descriptor short-circuit, and CHECK_ERROR
fail-safe when a check raises.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import pytest

from magi.availability.contracts import AvailabilityReason, AvailabilityResult
from magi.availability.resolver import AvailabilityResolver
from magi_plugin_sdk.contracts import (
    LocalizedText,
    LocalRequirementFileExists,
    PluginManifest,
    SuggestionDescriptor,
    Triggers,
)


def _provider_from(manifests: dict[str, PluginManifest]) -> Callable:
    return lambda plugin_id: manifests.get(plugin_id)


def test_resolver_returns_available_when_all_checks_pass(
    tmp_path: Path, make_manifest
) -> None:
    target = tmp_path / "x"
    target.write_text("")
    manifest = make_manifest(
        "p1",
        requirements=[
            LocalRequirementFileExists(
                check_kind="file_exists",
                paths_per_platform={
                    "darwin": str(target),
                    "win32": str(target),
                    "linux": str(target),
                },
            )
        ],
    )
    resolver = AvailabilityResolver(manifest_provider=_provider_from({"p1": manifest}))
    result = resolver.is_available("p1")
    assert isinstance(result, AvailabilityResult)
    assert result.available is True
    assert result.reason == AvailabilityReason.AVAILABLE


def test_resolver_returns_unavailable_for_missing_file(make_manifest, tmp_path: Path) -> None:
    manifest = make_manifest(
        "p2",
        requirements=[
            LocalRequirementFileExists(
                check_kind="file_exists",
                paths_per_platform={
                    "darwin": str(tmp_path / "nope"),
                    "win32": str(tmp_path / "nope"),
                    "linux": str(tmp_path / "nope"),
                },
            )
        ],
    )
    resolver = AvailabilityResolver(manifest_provider=_provider_from({"p2": manifest}))
    result = resolver.is_available("p2")
    assert result.available is False
    assert result.reason == AvailabilityReason.MISSING_FILE


def test_resolver_returns_unsupported_platform_when_filtered_out(
    make_manifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("magi.availability.checks._current_platform_key", lambda: "darwin")
    manifest = make_manifest("p3", platforms=["linux"])  # excludes darwin
    resolver = AvailabilityResolver(manifest_provider=_provider_from({"p3": manifest}))
    result = resolver.is_available("p3")
    assert result.available is False
    assert result.reason == AvailabilityReason.UNSUPPORTED_PLATFORM


def test_resolver_returns_no_descriptor_for_legacy_plugins(
    manifest_without_descriptor,
) -> None:
    resolver = AvailabilityResolver(
        manifest_provider=_provider_from({"legacy": manifest_without_descriptor})
    )
    result = resolver.is_available("legacy")
    assert result.available is False
    assert result.reason == AvailabilityReason.NO_DESCRIPTOR


def test_resolver_caches_results(make_manifest, tmp_path: Path) -> None:
    target = tmp_path / "x"
    target.write_text("")
    manifest = make_manifest(
        "p4",
        requirements=[
            LocalRequirementFileExists(
                check_kind="file_exists",
                paths_per_platform={"darwin": str(target), "win32": str(target), "linux": str(target)},
            )
        ],
    )
    resolver = AvailabilityResolver(manifest_provider=_provider_from({"p4": manifest}))

    import magi.availability.checks as checks_mod
    real_check = checks_mod.check_file_exists
    with patch("magi.availability.checks.check_file_exists", wraps=real_check) as spy:
        resolver.is_available("p4")
        resolver.is_available("p4")
        assert spy.call_count == 1  # second call hit cache


def test_resolver_invalidate_clears_cache(make_manifest, tmp_path: Path) -> None:
    target = tmp_path / "x"
    target.write_text("")
    manifest = make_manifest(
        "p5",
        requirements=[
            LocalRequirementFileExists(
                check_kind="file_exists",
                paths_per_platform={"darwin": str(target), "win32": str(target), "linux": str(target)},
            )
        ],
    )
    resolver = AvailabilityResolver(manifest_provider=_provider_from({"p5": manifest}))

    resolver.is_available("p5")
    resolver.invalidate("p5")

    import magi.availability.checks as checks_mod
    real_check = checks_mod.check_file_exists
    with patch("magi.availability.checks.check_file_exists", wraps=real_check) as spy:
        resolver.is_available("p5")
        assert spy.call_count == 1  # re-ran the check after invalidate


def test_resolver_ttl_expiry(make_manifest, tmp_path: Path) -> None:
    target = tmp_path / "x"
    target.write_text("")
    manifest = make_manifest(
        "p6",
        requirements=[
            LocalRequirementFileExists(
                check_kind="file_exists",
                paths_per_platform={"darwin": str(target), "win32": str(target), "linux": str(target)},
            )
        ],
    )
    resolver = AvailabilityResolver(
        manifest_provider=_provider_from({"p6": manifest}),
        ttl=timedelta(milliseconds=1),
    )
    resolver.is_available("p6")
    import time

    time.sleep(0.01)

    import magi.availability.checks as checks_mod
    real_check = checks_mod.check_file_exists
    with patch("magi.availability.checks.check_file_exists", wraps=real_check) as spy:
        resolver.is_available("p6")
        assert spy.call_count == 1  # cache expired, re-ran


def test_resolver_check_error_fails_safely(make_manifest, tmp_path: Path) -> None:
    """If a check raises unexpectedly, treat as unavailable with CHECK_ERROR reason."""
    target = tmp_path / "x"
    target.write_text("")
    manifest = make_manifest(
        "p7",
        requirements=[
            LocalRequirementFileExists(
                check_kind="file_exists",
                paths_per_platform={"darwin": str(target), "win32": str(target), "linux": str(target)},
            )
        ],
    )
    resolver = AvailabilityResolver(manifest_provider=_provider_from({"p7": manifest}))
    with patch(
        "magi.availability.checks.check_file_exists",
        side_effect=RuntimeError("disk on fire"),
    ):
        result = resolver.is_available("p7")
    assert result.available is False
    assert result.reason == AvailabilityReason.CHECK_ERROR
    assert "disk on fire" in (result.detail or "")


def test_resolver_unknown_plugin_id() -> None:
    resolver = AvailabilityResolver(manifest_provider=_provider_from({}))
    result = resolver.is_available("ghost")
    assert result.available is False
    assert result.reason == AvailabilityReason.NO_DESCRIPTOR


def test_resolver_list_available(make_manifest, tmp_path: Path) -> None:
    target = tmp_path / "x"
    target.write_text("")
    good = make_manifest(
        "good",
        requirements=[
            LocalRequirementFileExists(
                check_kind="file_exists",
                paths_per_platform={"darwin": str(target), "win32": str(target), "linux": str(target)},
            )
        ],
    )
    bad = make_manifest(
        "bad",
        requirements=[
            LocalRequirementFileExists(
                check_kind="file_exists",
                paths_per_platform={"darwin": "/nope", "win32": "/nope", "linux": "/nope"},
            )
        ],
    )
    resolver = AvailabilityResolver(
        manifest_provider=_provider_from({"good": good, "bad": bad})
    )
    available = resolver.list_available(plugin_ids=["good", "bad"])
    assert available == ["good"]
