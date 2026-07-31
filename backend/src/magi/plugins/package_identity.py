"""Canonical content identity for plugin package directories."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
import hmac
import os
from pathlib import Path
import re
import shutil
import stat

from magi_plugin_sdk.package_identity import (
    CanonicalPackagePath,
    INSTALLED_PACKAGE_IDENTITY_PROFILE,
    InvalidPackageIdentityPathError,
    PACKAGE_IDENTITY_DOMAIN,
    PACKAGE_IDENTITY_RECORD_DOMAIN,
    PACKAGE_IDENTITY_VERSION,
    PackageIdentityBuildError,
    PackageIdentityBuilder,
    PortablePathTracker,
    SOURCE_PACKAGE_IDENTITY_PROFILE,
)

_READ_CHUNK_BYTES = 1024 * 1024
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_SCAN_SOURCE = "source"
_SCAN_INSTALLED_SOURCE = "installed-source"
_SCAN_INSTALLED = "installed"
_WINDOWS_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class PluginPackageIdentityError(ValueError):
    """Base class for plugin package identity failures."""


class InvalidPluginPackageRootError(PluginPackageIdentityError):
    """Raised when the package root is missing or is not a real directory."""


class UnsafePluginPackageEntryError(PluginPackageIdentityError):
    """Raised when the package contains an unsafe or non-portable entry."""


class PluginPackageContentChangedError(PluginPackageIdentityError):
    """Raised when package content changes while its identity is calculated."""


class InvalidPluginPackageDigestError(PluginPackageIdentityError):
    """Raised when an expected package digest is not canonical SHA-256."""


class PluginPackageDigestMismatchError(PluginPackageIdentityError):
    """Raised when a package directory does not match its expected digest."""


@dataclass(frozen=True, slots=True)
class _PackageFile:
    path: Path
    identity_path: CanonicalPackagePath
    scanned_stat: os.stat_result

    @property
    def relative_path(self) -> str:
        return self.identity_path.relative_path

    @property
    def path_bytes(self) -> bytes:
        return self.identity_path.path_bytes


def compute_package_sha256(root: Path) -> str:
    """Return the canonical SHA-256 identity for a source plugin package."""

    return _compute_package_sha256(
        root,
        scan_profile=_SCAN_SOURCE,
        identity_profile=SOURCE_PACKAGE_IDENTITY_PROFILE,
    )


def compute_installed_source_sha256(root: Path) -> str:
    """Recompute a source package identity from an installed package tree."""

    return _compute_package_sha256(
        root,
        scan_profile=_SCAN_INSTALLED_SOURCE,
        identity_profile=SOURCE_PACKAGE_IDENTITY_PROFILE,
    )


def compute_installed_package_sha256(root: Path) -> str:
    """Seal all installed package files, including host-installed dependencies."""

    return _compute_package_sha256(
        root,
        scan_profile=_SCAN_INSTALLED,
        identity_profile=INSTALLED_PACKAGE_IDENTITY_PROFILE,
    )


def _compute_package_sha256(
    root: Path,
    *,
    scan_profile: str,
    identity_profile: bytes,
) -> str:
    package_root = _validate_package_root(Path(root))
    package_files = _collect_package_files(package_root, scan_profile=scan_profile)
    package_files.sort(key=lambda item: item.path_bytes)
    try:
        builder = PackageIdentityBuilder(
            profile=identity_profile,
            file_count=len(package_files),
        )
        for package_file in package_files:
            _add_package_file(builder, package_file)
    except PackageIdentityBuildError as exc:
        raise PluginPackageIdentityError(str(exc)) from exc

    rescanned_files = _collect_package_files(
        package_root,
        scan_profile=scan_profile,
    )
    rescanned_files.sort(key=lambda item: item.path_bytes)
    _require_package_inventory_unchanged(package_files, rescanned_files)

    try:
        return builder.hexdigest()
    except PackageIdentityBuildError as exc:
        raise PluginPackageIdentityError(str(exc)) from exc


def verify_package_sha256(
    root: Path,
    expected_sha256: str,
) -> None:
    """Require a source package to match a canonical lowercase SHA-256 digest."""

    expected = _validate_expected_sha256(expected_sha256)
    actual = compute_package_sha256(root)
    _require_expected_digest(actual, expected)


def verify_installed_source_sha256(root: Path, expected_sha256: str) -> None:
    """Require installed source files to match their upstream package identity."""

    expected = _validate_expected_sha256(expected_sha256)
    actual = compute_installed_source_sha256(root)
    _require_expected_digest(actual, expected)


def verify_installed_package_sha256(root: Path, expected_sha256: str) -> None:
    """Require the complete installed tree to match its local installation seal."""

    expected = _validate_expected_sha256(expected_sha256)
    actual = compute_installed_package_sha256(root)
    _require_expected_digest(actual, expected)


def _require_expected_digest(actual: str, expected: str) -> None:
    if not hmac.compare_digest(actual, expected):
        raise PluginPackageDigestMismatchError(
            f"Plugin package digest mismatch: expected {expected}, got {actual}"
        )


def purge_plugin_bytecode_caches(root: Path) -> None:
    """Remove host-generated Python cache directories without following links."""

    package_root = _validate_package_root(Path(root))
    pending_directories = [package_root]
    while pending_directories:
        directory = pending_directories.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
        except OSError as exc:
            raise PluginPackageContentChangedError(
                f"Plugin package directory cannot be read while clearing caches: {directory}: {exc}"
            ) from exc
        for entry in entries:
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise PluginPackageContentChangedError(
                    f"Plugin package entry cannot be inspected while clearing caches: "
                    f"{entry.path}: {exc}"
                ) from exc
            if _is_link_or_reparse_point(entry_stat):
                raise UnsafePluginPackageEntryError(
                    "Plugin package cannot contain symbolic links or Windows "
                    f"reparse points: {entry.path}"
                )
            if not stat.S_ISDIR(entry_stat.st_mode):
                continue
            entry_path = Path(entry.path)
            if entry.name.casefold() == "__pycache__":
                try:
                    shutil.rmtree(entry_path)
                except OSError as exc:
                    raise PluginPackageContentChangedError(
                        f"Plugin bytecode cache cannot be removed safely: {entry_path}: {exc}"
                    ) from exc
                continue
            pending_directories.append(entry_path)


def _validate_package_root(root: Path) -> Path:
    try:
        root_stat = root.lstat()
    except FileNotFoundError as exc:
        raise InvalidPluginPackageRootError(
            f"Plugin package directory does not exist: {root}"
        ) from exc
    except OSError as exc:
        raise InvalidPluginPackageRootError(
            f"Plugin package directory cannot be inspected: {root}: {exc}"
        ) from exc

    if _is_link_or_reparse_point(root_stat):
        raise InvalidPluginPackageRootError(
            "Plugin package directory cannot be a symbolic link or Windows "
            f"reparse point: {root}"
        )
    if not stat.S_ISDIR(root_stat.st_mode):
        raise InvalidPluginPackageRootError(f"Plugin package root must be a directory: {root}")
    return root


def _collect_package_files(
    root: Path,
    *,
    scan_profile: str,
) -> list[_PackageFile]:
    files: list[_PackageFile] = []
    path_tracker = PortablePathTracker()
    pending_directories: list[tuple[Path, tuple[str, ...]]] = [(root, ())]

    while pending_directories:
        directory, parent_parts = pending_directories.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
        except OSError as exc:
            relative = "/".join(parent_parts) or "."
            raise PluginPackageContentChangedError(
                f"Plugin package directory cannot be read: {relative}: {exc}"
            ) from exc

        for entry in entries:
            relative_parts = (*parent_parts, entry.name)
            try:
                identity_path = path_tracker.add(relative_parts)
            except InvalidPackageIdentityPathError as exc:
                raise UnsafePluginPackageEntryError(str(exc)) from exc
            relative_path = identity_path.relative_path
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise PluginPackageContentChangedError(
                    f"Plugin package entry cannot be inspected: {relative_path}: {exc}"
                ) from exc

            entry_mode = entry_stat.st_mode
            if _is_link_or_reparse_point(entry_stat):
                raise UnsafePluginPackageEntryError(
                    "Plugin package cannot contain symbolic links or Windows "
                    f"reparse points: {relative_path}"
                )

            is_directory = stat.S_ISDIR(entry_mode)
            is_regular_file = stat.S_ISREG(entry_mode)
            if not is_directory and not is_regular_file:
                raise UnsafePluginPackageEntryError(
                    f"Plugin package cannot contain special files: {relative_path}"
                )

            runtime_artifact = _runtime_artifact_kind(
                relative_parts,
                is_directory=is_directory,
            )
            if runtime_artifact is not None:
                if scan_profile == _SCAN_SOURCE:
                    raise UnsafePluginPackageEntryError(
                        f"Source plugin package contains a runtime artifact: {relative_path}"
                    )
                if runtime_artifact == "dependency-directory":
                    if scan_profile == _SCAN_INSTALLED_SOURCE and is_directory:
                        continue
                elif runtime_artifact == "bytecode-cache":
                    raise UnsafePluginPackageEntryError(
                        f"Plugin bytecode cache was not cleared before identity "
                        f"verification: {relative_path}"
                    )
                elif (
                    runtime_artifact == "loose-bytecode" and scan_profile == _SCAN_INSTALLED_SOURCE
                ):
                    # Loose bytecode is not a host cache directory. Include it so
                    # the upstream package comparison fails rather than ignoring
                    # executable content.
                    pass
                elif is_directory:
                    continue

            if is_directory:
                pending_directories.append((Path(entry.path), relative_parts))
                continue

            if entry_stat.st_nlink > 1:
                raise UnsafePluginPackageEntryError(
                    f"Plugin package cannot contain hard-linked files: {relative_path}"
                )
            files.append(
                _PackageFile(
                    path=Path(entry.path),
                    identity_path=identity_path,
                    scanned_stat=entry_stat,
                )
            )

    return files


def _is_link_or_reparse_point(entry_stat: os.stat_result) -> bool:
    """Return whether metadata identifies a link-like Windows or POSIX entry."""

    return stat.S_ISLNK(entry_stat.st_mode) or bool(
        getattr(entry_stat, "st_file_attributes", 0) & _WINDOWS_REPARSE_POINT_ATTRIBUTE
    )


def _runtime_artifact_kind(
    parts: tuple[str, ...],
    *,
    is_directory: bool,
) -> str | None:
    name = parts[-1]
    folded_name = name.casefold()
    if len(parts) == 1 and folded_name == ".deps":
        return "dependency-directory"
    if folded_name == "__pycache__":
        return "bytecode-cache"
    if not is_directory and folded_name.endswith((".pyc", ".pyo")):
        return "loose-bytecode"
    return None


def _add_package_file(
    builder: PackageIdentityBuilder,
    package_file: _PackageFile,
) -> None:
    chunks = _iter_package_file_chunks(package_file)
    with closing(chunks):
        builder.add_file(
            package_file.identity_path,
            content_size=package_file.scanned_stat.st_size,
            chunks=chunks,
        )


def _iter_package_file_chunks(package_file: _PackageFile) -> Iterator[bytes]:
    file_descriptor = _open_package_file(package_file)
    try:
        opened_stat = os.fstat(file_descriptor)
        _require_unchanged_regular_file(
            package_file,
            opened_stat,
            stage="before reading",
        )

        bytes_read = 0
        while True:
            chunk = os.read(file_descriptor, _READ_CHUNK_BYTES)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > opened_stat.st_size:
                raise PluginPackageContentChangedError(
                    f"Plugin package file changed while being read: {package_file.relative_path}"
                )
            yield chunk

        if bytes_read != opened_stat.st_size:
            raise PluginPackageContentChangedError(
                f"Plugin package file changed while being read: {package_file.relative_path}"
            )

        final_stat = os.fstat(file_descriptor)
        _require_same_file_state(
            opened_stat,
            final_stat,
            relative_path=package_file.relative_path,
            stage="while being read",
        )
        _require_path_still_references_file(package_file, final_stat)
    finally:
        os.close(file_descriptor)


def _open_package_file(package_file: _PackageFile) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(package_file.path, flags)
    except OSError as exc:
        raise PluginPackageContentChangedError(
            f"Plugin package file cannot be opened safely: {package_file.relative_path}: {exc}"
        ) from exc


def _require_unchanged_regular_file(
    package_file: _PackageFile,
    opened_stat: os.stat_result,
    *,
    stage: str,
) -> None:
    if not stat.S_ISREG(opened_stat.st_mode):
        raise UnsafePluginPackageEntryError(
            f"Plugin package entry is no longer a regular file: {package_file.relative_path}"
        )
    if opened_stat.st_nlink > 1:
        raise UnsafePluginPackageEntryError(
            f"Plugin package cannot contain hard-linked files: {package_file.relative_path}"
        )
    _require_same_file_state(
        package_file.scanned_stat,
        opened_stat,
        relative_path=package_file.relative_path,
        stage=stage,
    )


def _require_same_file_state(
    before: os.stat_result,
    after: os.stat_result,
    *,
    relative_path: str,
    stage: str,
) -> None:
    before_state = (
        before.st_dev,
        before.st_ino,
        stat.S_IFMT(before.st_mode),
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_state = (
        after.st_dev,
        after.st_ino,
        stat.S_IFMT(after.st_mode),
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if before_state != after_state:
        raise PluginPackageContentChangedError(
            f"Plugin package file changed {stage}: {relative_path}"
        )


def _require_path_still_references_file(
    package_file: _PackageFile,
    opened_stat: os.stat_result,
) -> None:
    try:
        path_stat = package_file.path.lstat()
    except OSError as exc:
        raise PluginPackageContentChangedError(
            f"Plugin package file moved while being read: {package_file.relative_path}: {exc}"
        ) from exc
    if _is_link_or_reparse_point(path_stat):
        raise UnsafePluginPackageEntryError(
            "Plugin package cannot contain symbolic links or Windows "
            f"reparse points: {package_file.relative_path}"
        )
    _require_same_file_state(
        opened_stat,
        path_stat,
        relative_path=package_file.relative_path,
        stage="while being read",
    )


def _require_package_inventory_unchanged(
    before: list[_PackageFile],
    after: list[_PackageFile],
) -> None:
    """Reject entry additions, removals, renames, or metadata changes during hashing."""

    if len(before) != len(after):
        raise PluginPackageContentChangedError(
            "Plugin package entries changed while its identity was calculated"
        )
    for before_file, after_file in zip(before, after, strict=True):
        if before_file.path_bytes != after_file.path_bytes or before_file.path != after_file.path:
            raise PluginPackageContentChangedError(
                "Plugin package entries changed while its identity was calculated"
            )
        _require_same_file_state(
            before_file.scanned_stat,
            after_file.scanned_stat,
            relative_path=before_file.relative_path,
            stage="while package identity was calculated",
        )


def _validate_expected_sha256(expected_sha256: str) -> str:
    if not isinstance(expected_sha256, str) or _SHA256_PATTERN.fullmatch(expected_sha256) is None:
        raise InvalidPluginPackageDigestError(
            "Expected plugin package digest must be 64 lowercase hexadecimal characters"
        )
    return expected_sha256


__all__ = [
    "InvalidPluginPackageDigestError",
    "InvalidPluginPackageRootError",
    "PACKAGE_IDENTITY_DOMAIN",
    "PACKAGE_IDENTITY_RECORD_DOMAIN",
    "PACKAGE_IDENTITY_VERSION",
    "INSTALLED_PACKAGE_IDENTITY_PROFILE",
    "SOURCE_PACKAGE_IDENTITY_PROFILE",
    "PluginPackageContentChangedError",
    "PluginPackageDigestMismatchError",
    "PluginPackageIdentityError",
    "UnsafePluginPackageEntryError",
    "compute_installed_package_sha256",
    "compute_installed_source_sha256",
    "compute_package_sha256",
    "purge_plugin_bytecode_caches",
    "verify_installed_package_sha256",
    "verify_installed_source_sha256",
    "verify_package_sha256",
]
