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


@pytest.mark.parametrize("entry", ["installed", "descriptor"])
@pytest.mark.parametrize(
    "case,reason",
    [
        ("present", AvailabilityReason.AVAILABLE),
        ("missing", AvailabilityReason.MISSING_FILE),
        ("unsupported", AvailabilityReason.UNSUPPORTED_PLATFORM),
    ],
)
def test_availability_entry_points_apply_platform_and_local_file_requirements(
    tmp_path, make_manifest, monkeypatch, entry, case, reason
):
    import magi.availability.checks as checks

    monkeypatch.setattr("magi.availability.resolver._current_platform_key", lambda: "darwin")
    monkeypatch.setattr(checks, "_current_platform_key", lambda: "darwin")
    target = tmp_path / "History"
    if case != "missing":
        target.write_text("History exists")
    platforms = ["linux"] if case == "unsupported" else ["darwin", "linux", "win32"]
    requirements = [
        LocalRequirementFileExists(
            check_kind="file_exists",
            paths_per_platform={"darwin": str(target), "linux": str(target), "win32": str(target)},
        )
    ]
    manifest = make_manifest("p1", requirements=requirements, platforms=platforms)
    resolver = AvailabilityResolver(
        manifest_provider=_provider_from({"p1": manifest} if entry == "installed" else {})
    )
    with patch(
        "magi.availability.checks.check_file_exists", wraps=checks.check_file_exists
    ) as check:
        result = (
            resolver.is_available("p1")
            if entry == "installed"
            else resolver.evaluate_descriptor(
                _descriptor(requirements=requirements, platforms=platforms), plugin_id="p1"
            )
        )
    assert isinstance(result, AvailabilityResult)
    assert (result.plugin_id, result.available, result.reason) == ("p1", case == "present", reason)
    assert check.call_count == (0 if case == "unsupported" else 1)


@pytest.mark.parametrize("plugin_id", ["legacy", "unknown"])
def test_missing_descriptor_fails_closed_for_known_and_unknown_plugins(
    manifest_without_descriptor,
    plugin_id,
) -> None:
    resolver = AvailabilityResolver(
        manifest_provider=_provider_from({"legacy": manifest_without_descriptor})
    )
    result = resolver.is_available(plugin_id)
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


# --- evaluate_descriptor: evaluate an arbitrary (not-installed) descriptor -----


def _descriptor(
    *,
    requirements: list | None = None,
    platforms: list[str] | None = None,
) -> SuggestionDescriptor:
    return SuggestionDescriptor(
        category="test_category",
        triggers=Triggers(intents=["x"]),
        platform_support=platforms or ["darwin", "win32", "linux"],
        local_requirements=requirements or [],
        rationale=LocalizedText(zh="测试", en="test"),
    )


def test_evaluate_descriptor_passes_plugin_id_through(tmp_path: Path) -> None:
    target = tmp_path / "x"
    target.write_text("")
    desc = _descriptor(
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
    resolver = AvailabilityResolver(manifest_provider=_provider_from({}))
    result = resolver.evaluate_descriptor(desc, plugin_id="registry-only-plugin")
    assert result.available is True
    assert result.plugin_id == "registry-only-plugin"
