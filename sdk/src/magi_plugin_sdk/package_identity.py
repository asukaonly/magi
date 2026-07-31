"""Portable, filesystem-independent plugin package identity contract."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import hashlib
import unicodedata

PACKAGE_IDENTITY_DOMAIN = b"magi.plugin.package.identity"
PACKAGE_IDENTITY_VERSION = b"1"
PACKAGE_IDENTITY_RECORD_DOMAIN = b"file"
SOURCE_PACKAGE_IDENTITY_PROFILE = b"source"
INSTALLED_PACKAGE_IDENTITY_PROFILE = b"installed"

WINDOWS_FORBIDDEN_PATH_CHARACTERS = frozenset('<>"|?*')
WINDOWS_RESERVED_PATH_STEMS = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)

_FRAME_LENGTH_BYTES = 8
_SUPPORTED_IDENTITY_PROFILES = frozenset(
    {
        SOURCE_PACKAGE_IDENTITY_PROFILE,
        INSTALLED_PACKAGE_IDENTITY_PROFILE,
    }
)


class PackageIdentityContractError(ValueError):
    """Base class for portable package identity contract failures."""


class InvalidPackageIdentityPathError(PackageIdentityContractError):
    """Raised when a package path is not portable or canonicalizable."""


class ConflictingPackageIdentityPathError(InvalidPackageIdentityPathError):
    """Raised when two source spellings collapse to one portable path."""


class PackageIdentityBuildError(PackageIdentityContractError):
    """Raised when canonical identity records are incomplete or out of order."""


@dataclass(frozen=True, slots=True)
class CanonicalPackagePath:
    """Canonical path material used by the package identity framing."""

    relative_path: str
    path_bytes: bytes
    portable_key: str


@dataclass(frozen=True, slots=True)
class PackageFile:
    """One distributable file backed by a repeatable or one-shot byte stream."""

    path: CanonicalPackagePath
    content_size: int
    chunks: Iterable[bytes | bytearray | memoryview]
    executable: bool = False


PackageIdentityFile = PackageFile


def windows_path_component_issue(component: str) -> str | None:
    """Return why one normalized path component is unsafe on Windows."""

    if ":" in component:
        return "contains a Windows drive or stream"
    if any(character in WINDOWS_FORBIDDEN_PATH_CHARACTERS for character in component):
        return "contains a Windows-forbidden character"
    if component.endswith((" ", ".")):
        return "has a non-portable trailing character"
    reserved_stem = component.rstrip(" .").split(".", 1)[0].casefold()
    if reserved_stem in WINDOWS_RESERVED_PATH_STEMS:
        return "uses a reserved Windows name"
    return None


def normalize_package_path_component(raw_component: str) -> str:
    """Validate and NFC-normalize one portable package path component."""

    if not isinstance(raw_component, str) or not raw_component:
        raise InvalidPackageIdentityPathError(
            "Package path contains an empty or non-text component"
        )
    if "/" in raw_component or "\\" in raw_component:
        raise InvalidPackageIdentityPathError(
            f"Package path component uses a non-portable separator: {raw_component}"
        )
    if "\x00" in raw_component or any(
        ord(character) < 32 for character in raw_component
    ):
        raise InvalidPackageIdentityPathError(
            f"Package path component contains control characters: {raw_component!r}"
        )

    normalized = unicodedata.normalize("NFC", raw_component)
    if normalized in {".", ".."}:
        raise InvalidPackageIdentityPathError(
            f"Package contains an unsafe path component: {raw_component}"
        )
    windows_issue = windows_path_component_issue(normalized)
    if windows_issue is not None:
        raise InvalidPackageIdentityPathError(
            f"Package path {windows_issue}: {raw_component}"
        )
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InvalidPackageIdentityPathError(
            f"Package path is not valid UTF-8 text: {raw_component!r}"
        ) from exc
    return normalized


class PortablePathTracker:
    """Canonicalize paths and reject spellings that collide across desktop filesystems."""

    def __init__(self) -> None:
        self._source_spellings: dict[str, str] = {}

    def add(self, parts: Sequence[str]) -> CanonicalPackagePath:
        """Register one raw relative path and return its canonical identity form."""

        source_parts = tuple(parts)
        canonical_path = canonicalize_package_path(source_parts)
        portable_parts = canonical_path.portable_key.split("/")

        for index in range(1, len(source_parts) + 1):
            portable_prefix = "/".join(portable_parts[:index])
            source_prefix = "/".join(source_parts[:index])
            previous = self._source_spellings.get(portable_prefix)
            if previous is not None and previous != source_prefix:
                display_path = "/".join(source_parts)
                raise ConflictingPackageIdentityPathError(
                    f"Package paths have conflicting portable spellings: {display_path}"
                )
            self._source_spellings[portable_prefix] = source_prefix

        return canonical_path


def canonicalize_package_path(parts: Sequence[str]) -> CanonicalPackagePath:
    """Return one canonical relative path without registering cross-path conflicts."""

    source_parts = tuple(parts)
    if not source_parts:
        raise InvalidPackageIdentityPathError("Package path cannot be empty")
    normalized_parts = tuple(
        normalize_package_path_component(part) for part in source_parts
    )
    relative_path = "/".join(normalized_parts)
    return CanonicalPackagePath(
        relative_path=relative_path,
        path_bytes=relative_path.encode("utf-8"),
        portable_key="/".join(part.casefold() for part in normalized_parts),
    )


class PackageIdentityBuilder:
    """Build one canonical package SHA-256 digest from sorted file streams."""

    def __init__(self, *, profile: bytes, file_count: int) -> None:
        if (
            not isinstance(profile, bytes)
            or profile not in _SUPPORTED_IDENTITY_PROFILES
        ):
            raise PackageIdentityBuildError("Unsupported package identity profile")
        _require_unsigned(file_count, field_name="file count")

        self._expected_file_count = file_count
        self._added_file_count = 0
        self._previous_path_bytes: bytes | None = None
        self._failed = False
        self._digest = hashlib.sha256()
        _hash_frame(self._digest, PACKAGE_IDENTITY_DOMAIN)
        _hash_frame(self._digest, PACKAGE_IDENTITY_VERSION)
        _hash_frame(self._digest, profile)
        _hash_frame(self._digest, _encode_unsigned(file_count))

    def add_file(
        self,
        path: CanonicalPackagePath,
        *,
        content_size: int,
        chunks: Iterable[bytes | bytearray | memoryview],
    ) -> None:
        """Add one file whose canonical path sorts after the previous file."""

        if self._failed:
            raise PackageIdentityBuildError("Package identity builder is unusable")
        try:
            self._add_file(path, content_size=content_size, chunks=chunks)
        except Exception:
            self._failed = True
            raise

    def _add_file(
        self,
        path: CanonicalPackagePath,
        *,
        content_size: int,
        chunks: Iterable[bytes | bytearray | memoryview],
    ) -> None:
        if self._added_file_count >= self._expected_file_count:
            raise PackageIdentityBuildError(
                "Package identity received more files than declared"
            )
        if not isinstance(path, CanonicalPackagePath):
            raise PackageIdentityBuildError("Package identity path is not canonical")
        if path.relative_path.encode("utf-8") != path.path_bytes:
            raise PackageIdentityBuildError("Canonical package path bytes do not match")
        if (
            self._previous_path_bytes is not None
            and path.path_bytes <= self._previous_path_bytes
        ):
            raise PackageIdentityBuildError(
                "Package identity files must use unique, strictly sorted paths"
            )
        _require_unsigned(content_size, field_name="file size")

        _hash_frame(self._digest, PACKAGE_IDENTITY_RECORD_DOMAIN)
        _hash_frame(self._digest, path.path_bytes)
        _hash_frame(self._digest, _encode_unsigned(content_size))

        bytes_read = 0
        for chunk in chunks:
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise PackageIdentityBuildError(
                    "Package identity content chunks must be bytes-like"
                )
            bytes_read += len(chunk)
            if bytes_read > content_size:
                raise PackageIdentityBuildError(
                    f"Package identity content exceeds its declared size: "
                    f"{path.relative_path}"
                )
            self._digest.update(chunk)
        if bytes_read != content_size:
            raise PackageIdentityBuildError(
                f"Package identity content does not match its declared size: "
                f"{path.relative_path}"
            )

        self._previous_path_bytes = path.path_bytes
        self._added_file_count += 1

    def hexdigest(self) -> str:
        """Return the digest after every declared file has been added."""

        if self._failed:
            raise PackageIdentityBuildError("Package identity builder is unusable")
        if self._added_file_count != self._expected_file_count:
            raise PackageIdentityBuildError(
                "Package identity did not receive every declared file"
            )
        return self._digest.hexdigest()


def compute_package_identity_sha256(
    files: Iterable[PackageFile],
    *,
    profile: bytes,
) -> str:
    """Sort canonical file inputs and return their streamed package identity."""

    ordered_files = sorted(files, key=lambda item: item.path.path_bytes)
    builder = PackageIdentityBuilder(
        profile=profile,
        file_count=len(ordered_files),
    )
    for package_file in ordered_files:
        builder.add_file(
            package_file.path,
            content_size=package_file.content_size,
            chunks=package_file.chunks,
        )
    return builder.hexdigest()


def _hash_frame(digest, payload: bytes) -> None:
    digest.update(_encode_unsigned(len(payload)))
    digest.update(payload)


def _require_unsigned(value: int, *, field_name: str) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value >= 1 << (_FRAME_LENGTH_BYTES * 8)
    ):
        raise PackageIdentityBuildError(
            f"Package identity {field_name} is outside the supported range"
        )


def _encode_unsigned(value: int) -> bytes:
    return value.to_bytes(_FRAME_LENGTH_BYTES, "big", signed=False)


__all__ = [
    "CanonicalPackagePath",
    "ConflictingPackageIdentityPathError",
    "INSTALLED_PACKAGE_IDENTITY_PROFILE",
    "InvalidPackageIdentityPathError",
    "PACKAGE_IDENTITY_DOMAIN",
    "PACKAGE_IDENTITY_RECORD_DOMAIN",
    "PACKAGE_IDENTITY_VERSION",
    "PackageIdentityBuildError",
    "PackageIdentityBuilder",
    "PackageIdentityContractError",
    "PackageIdentityFile",
    "PackageFile",
    "PortablePathTracker",
    "SOURCE_PACKAGE_IDENTITY_PROFILE",
    "WINDOWS_FORBIDDEN_PATH_CHARACTERS",
    "WINDOWS_RESERVED_PATH_STEMS",
    "canonicalize_package_path",
    "compute_package_identity_sha256",
    "normalize_package_path_component",
    "windows_path_component_issue",
]
