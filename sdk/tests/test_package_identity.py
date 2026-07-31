from __future__ import annotations

import unicodedata

import pytest

from magi_plugin_sdk.package_identity import (
    ConflictingPackageIdentityPathError,
    INSTALLED_PACKAGE_IDENTITY_PROFILE,
    InvalidPackageIdentityPathError,
    PackageFile,
    PackageIdentityBuildError,
    PackageIdentityBuilder,
    PortablePathTracker,
    SOURCE_PACKAGE_IDENTITY_PROFILE,
    compute_package_identity_sha256,
    normalize_package_path_component,
    windows_path_component_issue,
)


def _file(
    tracker: PortablePathTracker,
    parts: tuple[str, ...],
    content: bytes,
    *,
    executable: bool = False,
) -> PackageFile:
    return PackageFile(
        path=tracker.add(parts),
        content_size=len(content),
        chunks=(content,),
        executable=executable,
    )


def test_fixed_package_identity_vector_matches_host_contract() -> None:
    tracker = PortablePathTracker()
    files = [
        _file(
            tracker,
            ("scripts", "run.py"),
            b'print("ok")\n',
            executable=True,
        ),
        _file(tracker, ("plugin.toml",), b'id = "demo"\n'),
    ]

    assert (
        compute_package_identity_sha256(
            files,
            profile=SOURCE_PACKAGE_IDENTITY_PROFILE,
        )
        == "5b341aaf7c8be8205e00a5713bc8c41ad0ce67d757142e30790e94b6defae163"
    )


def test_executable_metadata_does_not_create_another_content_identity() -> None:
    first_tracker = PortablePathTracker()
    second_tracker = PortablePathTracker()
    content = b"#!/usr/bin/env python\n"

    non_executable = _file(first_tracker, ("run.py",), content)
    executable = _file(
        second_tracker,
        ("run.py",),
        content,
        executable=True,
    )

    assert compute_package_identity_sha256(
        [non_executable],
        profile=SOURCE_PACKAGE_IDENTITY_PROFILE,
    ) == compute_package_identity_sha256(
        [executable],
        profile=SOURCE_PACKAGE_IDENTITY_PROFILE,
    )


def test_content_chunk_boundaries_do_not_change_identity() -> None:
    first_tracker = PortablePathTracker()
    second_tracker = PortablePathTracker()
    first = PackageFile(
        path=first_tracker.add(("plugin.toml",)),
        content_size=6,
        chunks=(b"abcdef",),
    )
    second = PackageFile(
        path=second_tracker.add(("plugin.toml",)),
        content_size=6,
        chunks=(b"ab", memoryview(b"cd"), bytearray(b"ef")),
    )

    assert compute_package_identity_sha256(
        [first],
        profile=SOURCE_PACKAGE_IDENTITY_PROFILE,
    ) == compute_package_identity_sha256(
        [second],
        profile=SOURCE_PACKAGE_IDENTITY_PROFILE,
    )


def test_source_and_installed_profiles_have_distinct_identities() -> None:
    first_tracker = PortablePathTracker()
    second_tracker = PortablePathTracker()

    assert compute_package_identity_sha256(
        [_file(first_tracker, ("plugin.toml",), b"manifest")],
        profile=SOURCE_PACKAGE_IDENTITY_PROFILE,
    ) != compute_package_identity_sha256(
        [_file(second_tracker, ("plugin.toml",), b"manifest")],
        profile=INSTALLED_PACKAGE_IDENTITY_PROFILE,
    )


def test_builder_requires_unique_sorted_paths_and_complete_content() -> None:
    tracker = PortablePathTracker()
    earlier = tracker.add(("a.py",))
    later = tracker.add(("z.py",))

    out_of_order = PackageIdentityBuilder(
        profile=SOURCE_PACKAGE_IDENTITY_PROFILE,
        file_count=2,
    )
    out_of_order.add_file(later, content_size=1, chunks=(b"z",))
    with pytest.raises(PackageIdentityBuildError, match="strictly sorted"):
        out_of_order.add_file(earlier, content_size=1, chunks=(b"a",))

    incomplete_content = PackageIdentityBuilder(
        profile=SOURCE_PACKAGE_IDENTITY_PROFILE,
        file_count=1,
    )
    with pytest.raises(PackageIdentityBuildError, match="declared size"):
        incomplete_content.add_file(earlier, content_size=2, chunks=(b"a",))

    missing_file = PackageIdentityBuilder(
        profile=SOURCE_PACKAGE_IDENTITY_PROFILE,
        file_count=1,
    )
    with pytest.raises(PackageIdentityBuildError, match="every declared file"):
        missing_file.hexdigest()


@pytest.mark.parametrize(
    "component",
    [
        "",
        ".",
        "..",
        "nested/name",
        "nested\\name",
        "CON.txt",
        "trailing.",
        "trailing ",
        "stream:name",
        'quote"name',
        "less<name",
        "greater>name",
        "pipe|name",
        "question?name",
        "star*name",
        "control\x01name",
    ],
)
def test_path_component_contract_rejects_non_portable_names(component: str) -> None:
    with pytest.raises(InvalidPackageIdentityPathError):
        normalize_package_path_component(component)


def test_windows_path_rule_reports_the_specific_portability_issue() -> None:
    assert windows_path_component_issue("AUX.txt") == "uses a reserved Windows name"
    assert (
        windows_path_component_issue("stream:name")
        == "contains a Windows drive or stream"
    )
    assert windows_path_component_issue("ordinary.py") is None


def test_path_tracker_rejects_case_and_unicode_prefix_conflicts() -> None:
    case_tracker = PortablePathTracker()
    case_tracker.add(("Source", "first.py"))
    with pytest.raises(
        ConflictingPackageIdentityPathError,
        match="portable spellings",
    ):
        case_tracker.add(("source", "second.py"))

    nfc_name = unicodedata.normalize("NFC", "cafe\u0301")
    nfd_name = unicodedata.normalize("NFD", "cafe\u0301")
    unicode_tracker = PortablePathTracker()
    unicode_tracker.add((nfc_name, "first.py"))
    with pytest.raises(
        ConflictingPackageIdentityPathError,
        match="portable spellings",
    ):
        unicode_tracker.add((nfd_name, "second.py"))
