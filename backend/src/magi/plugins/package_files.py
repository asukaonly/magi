"""Filesystem operations for plugin package archives and install directories."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import gzip
import io
import logging
import os
from pathlib import Path
import shutil
import stat
import struct
import tarfile
import tempfile
import unicodedata
import uuid
import zipfile

from .operation_execution import serialize_plugin_archive_operation

logger = logging.getLogger(__name__)

MAX_PLUGIN_ARCHIVE_MEMBERS = 4096
MAX_PLUGIN_ARCHIVE_FILE_BYTES = 64 * 1024 * 1024
MAX_PLUGIN_ARCHIVE_TOTAL_BYTES = 256 * 1024 * 1024
MAX_PLUGIN_ARCHIVE_PATH_BYTES = 1024
MAX_PLUGIN_ARCHIVE_PATH_DEPTH = 32
MAX_PLUGIN_ARCHIVE_COMPONENT_BYTES = 255
MAX_PLUGIN_ARCHIVE_METADATA_BYTES = 16 * 1024 * 1024
MAX_PLUGIN_ARCHIVE_CONTAINER_BYTES = 288 * 1024 * 1024
MAX_PLUGIN_ARCHIVE_TAR_STREAM_BYTES = (
    MAX_PLUGIN_ARCHIVE_TOTAL_BYTES + MAX_PLUGIN_ARCHIVE_METADATA_BYTES
)
PLUGIN_ARCHIVE_COPY_CHUNK_BYTES = 1024 * 1024

_ZIP_END_RECORD = struct.Struct("<4s4H2LH")
_ZIP_END_SIGNATURE = b"PK\x05\x06"
_ZIP_CENTRAL_HEADER_BYTES = 46
_ZIP_CENTRAL_SIGNATURE = b"PK\x01\x02"
_ZIP_MAX_COMMENT_BYTES = (1 << 16) - 1
_ZIP_SENTINEL_16 = (1 << 16) - 1
_ZIP_SENTINEL_32 = (1 << 32) - 1

_WINDOWS_RESERVED_PATH_STEMS = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class InvalidPluginArchiveError(ValueError):
    """Raised when an uploaded plugin archive is unsupported, corrupt, or unsafe."""


class _BoundedTarParserFile:
    """Limit bytes tarfile may read while it inventories archive metadata."""

    def __init__(self, fileobj) -> None:
        self._fileobj = fileobj
        self._remaining = MAX_PLUGIN_ARCHIVE_METADATA_BYTES
        self._limited = True

    def read(self, size: int = -1) -> bytes:
        if self._limited:
            if size < 0 or size > self._remaining:
                raise InvalidPluginArchiveError("Archive exceeds the TAR metadata parsing limit")
            data = self._fileobj.read(size)
            self._remaining -= len(data)
            return data
        return self._fileobj.read(size)

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        return self._fileobj.seek(offset, whence)

    def tell(self) -> int:
        return self._fileobj.tell()

    def allow_file_reads(self) -> None:
        self._limited = False


@dataclass(frozen=True, slots=True)
class _PlannedArchiveMember:
    archive_member: tarfile.TarInfo | zipfile.ZipInfo
    relative_path: Path
    portable_key: str
    is_dir: bool
    size: int
    executable: bool


class _ArchivePlan:
    """Validate an archive inventory completely before writing any member."""

    def __init__(self) -> None:
        self.members: list[_PlannedArchiveMember] = []
        self._seen_paths: set[str] = set()
        self._file_paths: set[str] = set()
        self._portable_path_spellings: dict[str, str] = {}
        self._total_bytes = 0
        self._member_count = 0

    def add(
        self,
        *,
        archive_member: tarfile.TarInfo | zipfile.ZipInfo,
        raw_name: str,
        is_dir: bool,
        size: int,
        executable: bool,
    ) -> None:
        self._member_count += 1
        if self._member_count > MAX_PLUGIN_ARCHIVE_MEMBERS:
            raise InvalidPluginArchiveError(
                f"Archive contains more than {MAX_PLUGIN_ARCHIVE_MEMBERS} members"
            )

        normalized = _normalize_archive_member_path(raw_name, is_dir=is_dir)
        if normalized is None:
            return
        relative_path, portable_key = normalized

        if portable_key in self._seen_paths:
            raise InvalidPluginArchiveError(
                f"Duplicate or case-conflicting archive path: {raw_name}"
            )

        exact_parts = [unicodedata.normalize("NFC", part) for part in relative_path.parts]
        portable_parts = portable_key.split("/")
        for index in range(1, len(portable_parts) + 1):
            portable_prefix = "/".join(portable_parts[:index])
            exact_prefix = "/".join(exact_parts[:index])
            previous_spelling = self._portable_path_spellings.get(portable_prefix)
            if previous_spelling is not None and previous_spelling != exact_prefix:
                raise InvalidPluginArchiveError(
                    f"Archive paths have conflicting portable spellings: {raw_name}"
                )
            self._portable_path_spellings[portable_prefix] = exact_prefix

        key_parts = portable_key.split("/")
        for index in range(1, len(key_parts)):
            parent_key = "/".join(key_parts[:index])
            if parent_key in self._file_paths:
                raise InvalidPluginArchiveError(f"Archive path is nested below a file: {raw_name}")
        if not is_dir and any(
            existing.startswith(f"{portable_key}/") for existing in self._seen_paths
        ):
            raise InvalidPluginArchiveError(
                f"Archive file conflicts with an existing directory: {raw_name}"
            )

        if size < 0:
            raise InvalidPluginArchiveError(f"Archive member has a negative size: {raw_name}")
        if is_dir and size:
            raise InvalidPluginArchiveError(
                f"Archive directory unexpectedly contains data: {raw_name}"
            )
        if not is_dir:
            if size > MAX_PLUGIN_ARCHIVE_FILE_BYTES:
                raise InvalidPluginArchiveError(
                    f"Archive member exceeds the per-file limit: {raw_name}"
                )
            self._total_bytes += size
            if self._total_bytes > MAX_PLUGIN_ARCHIVE_TOTAL_BYTES:
                raise InvalidPluginArchiveError("Archive exceeds the total expanded-size limit")

        self._seen_paths.add(portable_key)
        if not is_dir:
            self._file_paths.add(portable_key)
        self.members.append(
            _PlannedArchiveMember(
                archive_member=archive_member,
                relative_path=relative_path,
                portable_key=portable_key,
                is_dir=is_dir,
                size=size,
                executable=executable,
            )
        )


def user_plugins_root() -> Path:
    return Path("~/.magi/plugins").expanduser()


def managed_plugin_directory(plugin_id: str) -> Path:
    """Return the resolved host-owned directory for one plugin id."""

    return user_plugins_root().expanduser().resolve(strict=False) / plugin_id


def is_user_plugins_root(path: Path) -> bool:
    """Return whether a search root is the host-owned plugin directory."""

    return path.expanduser().resolve(strict=False) == user_plugins_root().expanduser().resolve(
        strict=False
    )


def is_managed_plugin_manifest_path(plugin_id: str, manifest_path: Path | str) -> bool:
    """Require ``<managed-root>/<plugin-id>/plugin.toml`` without symlink indirection."""

    expected_dir = managed_plugin_directory(plugin_id)
    expected_manifest = expected_dir / "plugin.toml"
    candidate = Path(manifest_path).expanduser()
    candidate_dir = candidate.parent
    if candidate.is_symlink() or candidate_dir.is_symlink():
        return False
    return (
        candidate.resolve(strict=False) == expected_manifest
        and candidate_dir.resolve(strict=False) == expected_dir
        and expected_dir.parent == user_plugins_root().expanduser().resolve(strict=False)
    )


def replace_plugin_directory(
    source_dir: Path,
    dest_dir: Path,
    *,
    prepare_staging_dir: Callable[[Path], None] | None = None,
    before_swap: Callable[[], None] | None = None,
    after_swap: Callable[[], None] | None = None,
    after_rollback: Callable[[], None] | None = None,
) -> None:
    """Replace a plugin directory while retaining the old tree until commit.

    ``after_swap`` runs while the previous directory is still available as a
    private backup. If promotion or post-swap validation fails, the filesystem
    is restored first and ``after_rollback`` can rebuild matching runtime
    state. The backup is deleted only after ``after_swap`` succeeds.
    """

    staging_dir = stage_plugin_directory(
        source_dir,
        dest_dir,
        prepare_staging_dir=prepare_staging_dir,
    )
    try:
        backup_dir = promote_staged_plugin_directory(
            staging_dir,
            dest_dir,
            before_swap=before_swap,
            after_swap=after_swap,
            after_rollback=after_rollback,
        )
    finally:
        discard_plugin_transaction_directory(staging_dir)
    discard_plugin_transaction_directory(backup_dir)


def stage_plugin_directory(
    source_dir: Path,
    dest_dir: Path,
    *,
    prepare_staging_dir: Callable[[Path], None] | None = None,
) -> Path:
    """Copy and prepare a package outside its discoverable install root."""

    parent_dir = dest_dir.parent
    parent_dir.mkdir(parents=True, exist_ok=True)

    transaction_root = parent_dir.parent
    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{parent_dir.name}-{dest_dir.name}-staging-",
            dir=transaction_root,
        )
    )

    try:
        logger.info(
            "Staging plugin directory",
            extra={
                "source_dir": str(source_dir),
                "dest_dir": str(dest_dir),
                "staging_dir": str(staging_dir),
            },
        )
        shutil.rmtree(staging_dir)
        shutil.copytree(source_dir, staging_dir)

        if prepare_staging_dir is not None:
            prepare_staging_dir(staging_dir)
        return staging_dir
    except BaseException:
        discard_plugin_transaction_directory(staging_dir)
        raise


def promote_staged_plugin_directory(
    staging_dir: Path,
    dest_dir: Path,
    *,
    before_swap: Callable[[], None] | None = None,
    after_swap: Callable[[], None] | None = None,
    after_rollback: Callable[[], None] | None = None,
) -> Path | None:
    """Atomically publish a prepared package and return its private backup.

    The caller owns cleanup of the returned backup. Keeping that potentially
    slow deletion outside this function lets lifecycle callers release their
    state lock immediately after the new package is fully committed.
    """

    parent_dir = dest_dir.parent
    parent_dir.mkdir(parents=True, exist_ok=True)
    if not staging_dir.is_dir():
        raise RuntimeError("Prepared plugin directory is unavailable")

    backup_dir = parent_dir.parent / f".{parent_dir.name}-{dest_dir.name}-backup-{uuid.uuid4().hex}"
    lifecycle_started = False
    backup_created = False
    promoted = False

    try:
        if before_swap is not None:
            lifecycle_started = True
            before_swap()

        if dest_dir.exists():
            logger.info(
                "Backing up existing plugin directory",
                extra={"dest_dir": str(dest_dir), "backup_dir": str(backup_dir)},
            )
            dest_dir.replace(backup_dir)
            backup_created = True

        staging_dir.replace(dest_dir)
        promoted = True
        logger.info(
            "Promoted staged plugin directory",
            extra={"dest_dir": str(dest_dir), "staging_dir": str(staging_dir)},
        )

        if after_swap is not None:
            after_swap()
        return backup_dir if backup_dir.exists() else None
    except BaseException as operation_error:
        if lifecycle_started or backup_created or promoted:
            try:
                if promoted and dest_dir.exists():
                    shutil.rmtree(dest_dir)
                if backup_created and backup_dir.exists():
                    backup_dir.replace(dest_dir)
                if after_rollback is not None:
                    after_rollback()
            except BaseException as rollback_error:
                logger.critical(
                    "Plugin directory rollback failed",
                    extra={
                        "dest_dir": str(dest_dir),
                        "backup_dir": str(backup_dir),
                        "operation_error": str(operation_error),
                        "rollback_error": str(rollback_error),
                    },
                    exc_info=True,
                )
                raise RuntimeError(
                    f"Plugin installation failed and rollback could not be completed: "
                    f"{operation_error}"
                ) from rollback_error
        raise


def discard_plugin_transaction_directory(directory: Path | None) -> None:
    """Best-effort cleanup for one private plugin transaction directory."""

    if directory is not None and directory.exists():
        shutil.rmtree(directory, ignore_errors=True)


@serialize_plugin_archive_operation
def extract_plugin_archive(archive_path: Path, dest: Path) -> None:
    """Safely extract one plugin archive into an empty destination."""

    name = archive_path.name.lower()
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        _validate_archive_container_size(archive_path)
        try:
            with tempfile.TemporaryFile() as tar_stream:
                _stage_bounded_tar_stream(archive_path, tar_stream)
                bounded_tar_stream = _BoundedTarParserFile(tar_stream)
                with tarfile.open(fileobj=bounded_tar_stream, mode="r:") as tf:
                    plan = _build_tar_archive_plan(tf)
                    root = _prepare_archive_destination(dest)
                    bounded_tar_stream.allow_file_reads()
                    _extract_tar_archive_plan(tf, plan, root)
        except (tarfile.TarError, gzip.BadGzipFile, EOFError) as exc:
            raise InvalidPluginArchiveError(f"Not a valid .tar.gz archive: {exc}") from exc
        return

    if name.endswith(".zip"):
        _validate_archive_container_size(archive_path)
        _validate_zip_directory(archive_path)
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                plan = _build_zip_archive_plan(zf)
                root = _prepare_archive_destination(dest)
                _extract_zip_archive_plan(zf, plan, root)
        except (
            zipfile.BadZipFile,
            zipfile.LargeZipFile,
            RuntimeError,
            NotImplementedError,
            EOFError,
        ) as exc:
            raise InvalidPluginArchiveError(f"Not a valid .zip archive: {exc}") from exc
        return

    raise InvalidPluginArchiveError(f"Unsupported archive format: {archive_path.name}")


def extract_plugin_subdirectory_tarball(
    tarball_bytes: bytes,
    subdir: str,
    dest: Path,
) -> None:
    """Safely extract one registry package from a bounded repository tarball.

    Callers must already hold a plugin preparation slot. This helper stays
    undecorated so registry preparation never reverses the archive-lock then
    preparation-slot order used by uploaded archives.
    """

    normalized_subdir = _normalize_registry_subdirectory(subdir)
    try:
        with tempfile.TemporaryFile() as tar_stream:
            with gzip.GzipFile(fileobj=io.BytesIO(tarball_bytes), mode="rb") as source:
                _copy_bounded_tar_stream(source, tar_stream)
            bounded_tar_stream = _BoundedTarParserFile(tar_stream)
            with tarfile.open(fileobj=bounded_tar_stream, mode="r:") as tf:
                plan = _build_registry_tar_archive_plan(tf, normalized_subdir)
                root = _prepare_archive_destination(dest)
                bounded_tar_stream.allow_file_reads()
                _extract_tar_archive_plan(tf, plan, root)
    except (tarfile.TarError, gzip.BadGzipFile, EOFError) as exc:
        raise InvalidPluginArchiveError(f"Not a valid registry tarball: {exc}") from exc


def _validate_archive_container_size(archive_path: Path) -> None:
    if archive_path.stat().st_size > MAX_PLUGIN_ARCHIVE_CONTAINER_BYTES:
        raise InvalidPluginArchiveError(
            f"Archive exceeds the {MAX_PLUGIN_ARCHIVE_CONTAINER_BYTES}-byte container limit"
        )


def _stage_bounded_tar_stream(archive_path: Path, destination) -> None:
    with gzip.open(archive_path, "rb") as source:
        _copy_bounded_tar_stream(source, destination)


def _copy_bounded_tar_stream(source, destination) -> None:
    total_bytes = 0
    while chunk := source.read(PLUGIN_ARCHIVE_COPY_CHUNK_BYTES):
        total_bytes += len(chunk)
        if total_bytes > MAX_PLUGIN_ARCHIVE_TAR_STREAM_BYTES:
            raise InvalidPluginArchiveError("Archive exceeds the expanded TAR stream limit")
        destination.write(chunk)
    destination.flush()
    destination.seek(0)


def _normalize_registry_subdirectory(subdir: str) -> str:
    normalized = subdir.replace("\\", "/").strip("/")
    if (
        not normalized
        or subdir.startswith(("/", "\\"))
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        raise InvalidPluginArchiveError("Registry plugin path is invalid")
    _normalize_archive_member_path(f"{normalized}/placeholder", is_dir=False)
    return normalized


def _build_registry_tar_archive_plan(
    tf: tarfile.TarFile,
    subdir: str,
) -> _ArchivePlan:
    plan = _ArchivePlan()
    top_prefix: str | None = None
    target_prefix: str | None = None
    scanned_members = 0
    matched_members = 0

    for member in tf:
        scanned_members += 1
        if scanned_members > MAX_PLUGIN_ARCHIVE_MEMBERS:
            raise InvalidPluginArchiveError(
                f"Archive contains more than {MAX_PLUGIN_ARCHIVE_MEMBERS} members"
            )
        if top_prefix is None:
            first_name = member.name.replace("\\", "/")
            if first_name.startswith("/") or not first_name.strip("/"):
                raise InvalidPluginArchiveError("Registry tarball has an invalid root path")
            root_component = first_name.split("/", 1)[0]
            _normalize_archive_member_path(
                f"{root_component}/placeholder",
                is_dir=False,
            )
            top_prefix = f"{root_component}/"
            target_prefix = f"{top_prefix}{subdir.rstrip('/')}/"

        assert target_prefix is not None
        normalized_name = member.name.replace("\\", "/")
        if not normalized_name.startswith(target_prefix):
            continue
        relative_name = normalized_name[len(target_prefix) :]
        if not relative_name:
            continue
        if not (member.isfile() or member.isdir()):
            raise InvalidPluginArchiveError(
                f"Archive member is not a regular file or directory: {member.name}"
            )
        plan.add(
            archive_member=member,
            raw_name=relative_name,
            is_dir=member.isdir(),
            size=member.size,
            executable=bool(member.mode & 0o111),
        )
        matched_members += 1

    if matched_members == 0:
        raise InvalidPluginArchiveError(
            f"Plugin path '{subdir}' was not found in the registry tarball"
        )
    return plan


def _validate_zip_directory(archive_path: Path) -> None:
    """Bound and validate the ZIP inventory before zipfile allocates it."""

    archive_size = archive_path.stat().st_size
    tail_size = min(
        archive_size,
        _ZIP_END_RECORD.size + _ZIP_MAX_COMMENT_BYTES,
    )
    with archive_path.open("rb") as archive:
        archive.seek(archive_size - tail_size)
        tail = archive.read(tail_size)
        end_record = _find_zip_end_record(tail)
        if end_record is None:
            raise InvalidPluginArchiveError("Not a valid .zip archive: end record is missing")

        end_offset_in_tail, end_values = end_record
        (
            _signature,
            disk_number,
            central_disk_number,
            entries_on_disk,
            total_entries,
            central_size,
            central_offset,
            _comment_size,
        ) = end_values
        if disk_number != 0 or central_disk_number != 0 or entries_on_disk != total_entries:
            raise InvalidPluginArchiveError("Multi-disk ZIP archives are not supported")
        if (
            total_entries == _ZIP_SENTINEL_16
            or central_size == _ZIP_SENTINEL_32
            or central_offset == _ZIP_SENTINEL_32
        ):
            raise InvalidPluginArchiveError("ZIP64 plugin archives are not supported")
        if total_entries > MAX_PLUGIN_ARCHIVE_MEMBERS:
            raise InvalidPluginArchiveError(
                f"Archive contains more than {MAX_PLUGIN_ARCHIVE_MEMBERS} members"
            )
        if central_size > MAX_PLUGIN_ARCHIVE_METADATA_BYTES:
            raise InvalidPluginArchiveError("Archive ZIP directory exceeds the metadata limit")

        end_offset = archive_size - tail_size + end_offset_in_tail
        if central_offset + central_size != end_offset:
            raise InvalidPluginArchiveError("Archive ZIP directory has invalid bounds")

        archive.seek(central_offset)
        parsed_entries = _count_zip_directory_entries(
            archive,
            central_size=central_size,
        )
        if parsed_entries != total_entries:
            raise InvalidPluginArchiveError("Archive ZIP directory entry count is inconsistent")


def _find_zip_end_record(
    tail: bytes,
) -> tuple[int, tuple[bytes, int, int, int, int, int, int, int]] | None:
    search_end = len(tail)
    while True:
        offset = tail.rfind(_ZIP_END_SIGNATURE, 0, search_end)
        if offset < 0:
            return None
        if offset + _ZIP_END_RECORD.size <= len(tail):
            values = _ZIP_END_RECORD.unpack_from(tail, offset)
            comment_size = values[-1]
            if offset + _ZIP_END_RECORD.size + comment_size == len(tail):
                return offset, values
        search_end = offset


def _count_zip_directory_entries(archive, *, central_size: int) -> int:
    remaining = central_size
    count = 0
    while remaining:
        if remaining < _ZIP_CENTRAL_HEADER_BYTES:
            raise InvalidPluginArchiveError("Archive ZIP directory is truncated")
        header = archive.read(_ZIP_CENTRAL_HEADER_BYTES)
        if len(header) != _ZIP_CENTRAL_HEADER_BYTES or header[:4] != _ZIP_CENTRAL_SIGNATURE:
            raise InvalidPluginArchiveError("Archive ZIP directory contains an invalid entry")

        name_size, extra_size, comment_size = struct.unpack_from("<HHH", header, 28)
        variable_size = name_size + extra_size + comment_size
        record_size = _ZIP_CENTRAL_HEADER_BYTES + variable_size
        if record_size > remaining:
            raise InvalidPluginArchiveError("Archive ZIP directory entry exceeds its bounds")
        archive.seek(variable_size, os.SEEK_CUR)
        remaining -= record_size
        count += 1
        if count > MAX_PLUGIN_ARCHIVE_MEMBERS:
            raise InvalidPluginArchiveError(
                f"Archive contains more than {MAX_PLUGIN_ARCHIVE_MEMBERS} members"
            )
    return count


def _build_tar_archive_plan(tf: tarfile.TarFile) -> _ArchivePlan:
    plan = _ArchivePlan()
    for member in tf:
        if not (member.isfile() or member.isdir()):
            raise InvalidPluginArchiveError(
                f"Archive member is not a regular file or directory: {member.name}"
            )
        plan.add(
            archive_member=member,
            raw_name=member.name,
            is_dir=member.isdir(),
            size=member.size,
            executable=bool(member.mode & 0o111),
        )
    return plan


def _build_zip_archive_plan(zf: zipfile.ZipFile) -> _ArchivePlan:
    plan = _ArchivePlan()
    for info in zf.infolist():
        unix_mode = info.external_attr >> 16
        file_type = stat.S_IFMT(unix_mode)
        is_dir = info.is_dir()
        allowed_types = {0, stat.S_IFDIR if is_dir else stat.S_IFREG}
        if file_type not in allowed_types:
            raise InvalidPluginArchiveError(
                f"Archive member is not a regular file or directory: {info.filename}"
            )
        if info.flag_bits & 0x1:
            raise InvalidPluginArchiveError(
                f"Encrypted archive members are not supported: {info.filename}"
            )
        plan.add(
            archive_member=info,
            raw_name=info.filename,
            is_dir=is_dir,
            size=info.file_size,
            executable=not is_dir and bool(unix_mode & 0o111),
        )
    return plan


def _normalize_archive_member_path(
    raw_name: str,
    *,
    is_dir: bool,
) -> tuple[Path, str] | None:
    if not isinstance(raw_name, str) or not raw_name:
        raise InvalidPluginArchiveError("Archive contains an empty path")
    if "\x00" in raw_name or any(ord(character) < 32 for character in raw_name):
        raise InvalidPluginArchiveError(f"Archive path contains control characters: {raw_name!r}")
    if "\\" in raw_name:
        raise InvalidPluginArchiveError(f"Archive path uses a non-portable separator: {raw_name}")

    normalized_name = raw_name
    while normalized_name.startswith("./"):
        normalized_name = normalized_name[2:]
    if is_dir and normalized_name in {"", "."}:
        return None
    if normalized_name.startswith("/"):
        raise InvalidPluginArchiveError(f"Archive path is absolute: {raw_name}")
    if is_dir and normalized_name.endswith("/"):
        normalized_name = normalized_name[:-1]
    if not normalized_name or normalized_name.endswith("/"):
        raise InvalidPluginArchiveError(f"Archive contains an invalid path: {raw_name}")

    try:
        encoded_path = normalized_name.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InvalidPluginArchiveError(
            f"Archive path is not valid UTF-8 text: {raw_name!r}"
        ) from exc
    if len(encoded_path) > MAX_PLUGIN_ARCHIVE_PATH_BYTES:
        raise InvalidPluginArchiveError(f"Archive path is too long: {raw_name}")

    parts = normalized_name.split("/")
    if len(parts) > MAX_PLUGIN_ARCHIVE_PATH_DEPTH:
        raise InvalidPluginArchiveError(f"Archive path is too deep: {raw_name}")

    portable_parts: list[str] = []
    for part in parts:
        if part in {"", ".", ".."}:
            raise InvalidPluginArchiveError(f"Archive contains an unsafe path: {raw_name}")
        if ":" in part:
            raise InvalidPluginArchiveError(
                f"Archive path contains a Windows drive or stream: {raw_name}"
            )
        if part.endswith((" ", ".")):
            raise InvalidPluginArchiveError(
                f"Archive path has a non-portable trailing character: {raw_name}"
            )
        try:
            encoded_part = part.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise InvalidPluginArchiveError(
                f"Archive path component is not valid UTF-8 text: {raw_name!r}"
            ) from exc
        if len(encoded_part) > MAX_PLUGIN_ARCHIVE_COMPONENT_BYTES:
            raise InvalidPluginArchiveError(f"Archive path component is too long: {raw_name}")
        reserved_stem = part.rstrip(" .").split(".", 1)[0].casefold()
        if reserved_stem in _WINDOWS_RESERVED_PATH_STEMS:
            raise InvalidPluginArchiveError(
                f"Archive path uses a reserved Windows name: {raw_name}"
            )
        portable_parts.append(unicodedata.normalize("NFC", part).casefold())

    relative_path = Path(*parts)
    portable_key = "/".join(portable_parts)
    return relative_path, portable_key


def _prepare_archive_destination(dest: Path) -> Path:
    if dest.is_symlink():
        raise InvalidPluginArchiveError("Archive destination cannot be a symlink")
    if dest.exists() and not dest.is_dir():
        raise InvalidPluginArchiveError("Archive destination must be a directory")
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.iterdir()):
        raise InvalidPluginArchiveError("Archive destination must be empty")
    return dest.resolve(strict=True)


def _extract_tar_archive_plan(
    tf: tarfile.TarFile,
    plan: _ArchivePlan,
    root: Path,
) -> None:
    total_written = 0
    for planned in plan.members:
        member = planned.archive_member
        assert isinstance(member, tarfile.TarInfo)
        target = _prepare_member_target(root, planned)
        if planned.is_dir:
            continue
        source = tf.extractfile(member)
        if source is None:
            raise InvalidPluginArchiveError(f"Archive member could not be read: {member.name}")
        with source:
            total_written = _copy_archive_member(
                source,
                target,
                expected_size=planned.size,
                executable=planned.executable,
                total_written=total_written,
            )


def _extract_zip_archive_plan(
    zf: zipfile.ZipFile,
    plan: _ArchivePlan,
    root: Path,
) -> None:
    total_written = 0
    for planned in plan.members:
        info = planned.archive_member
        assert isinstance(info, zipfile.ZipInfo)
        target = _prepare_member_target(root, planned)
        if planned.is_dir:
            continue
        with zf.open(info, "r") as source:
            total_written = _copy_archive_member(
                source,
                target,
                expected_size=planned.size,
                executable=planned.executable,
                total_written=total_written,
            )


def _prepare_member_target(root: Path, planned: _PlannedArchiveMember) -> Path:
    target = root / planned.relative_path
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    resolved_parent = target.parent.resolve(strict=True)
    if not resolved_parent.is_relative_to(root):
        raise InvalidPluginArchiveError(
            f"Archive member escapes the destination: {planned.relative_path}"
        )

    if planned.is_dir:
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            raise InvalidPluginArchiveError(
                f"Archive directory conflicts with an existing path: {planned.relative_path}"
            )
        target.mkdir(parents=True, exist_ok=True, mode=0o755)
        target.chmod(0o755)
        return target

    if target.exists() or target.is_symlink():
        raise InvalidPluginArchiveError(
            f"Archive file conflicts with an existing path: {planned.relative_path}"
        )
    return target


def _copy_archive_member(
    source,
    target: Path,
    *,
    expected_size: int,
    executable: bool,
    total_written: int,
) -> int:
    file_written = 0
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as destination:
            descriptor = -1
            while chunk := source.read(PLUGIN_ARCHIVE_COPY_CHUNK_BYTES):
                next_file_size = file_written + len(chunk)
                next_total_size = total_written + len(chunk)
                if (
                    next_file_size > expected_size
                    or next_file_size > MAX_PLUGIN_ARCHIVE_FILE_BYTES
                    or next_total_size > MAX_PLUGIN_ARCHIVE_TOTAL_BYTES
                ):
                    raise InvalidPluginArchiveError(
                        f"Archive member exceeds its declared or allowed size: {target.name}"
                    )
                destination.write(chunk)
                file_written = next_file_size
                total_written = next_total_size
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if file_written != expected_size:
        raise InvalidPluginArchiveError(
            f"Archive member size does not match its declaration: {target.name}"
        )
    target.chmod(0o755 if executable else 0o644)
    return total_written


def resolve_plugin_package_root(root: Path) -> Path | None:
    """Return the only valid package root below an extracted archive root."""

    if not root.exists():
        return None
    if root.is_symlink() or not root.is_dir():
        raise InvalidPluginArchiveError("Plugin package root must be a real directory")

    manifests = sorted(root.rglob("plugin.toml"))
    if not manifests:
        return None
    if len(manifests) != 1:
        raise InvalidPluginArchiveError("Archive must contain exactly one plugin.toml")

    manifest = manifests[0]
    if manifest.is_symlink() or not manifest.is_file():
        raise InvalidPluginArchiveError("plugin.toml must be a regular file")
    relative_manifest = manifest.relative_to(root)
    if relative_manifest.parts == ("plugin.toml",):
        return root
    if len(relative_manifest.parts) != 2:
        raise InvalidPluginArchiveError(
            "plugin.toml must be at the archive root or one directory below it"
        )

    package_root = root / relative_manifest.parts[0]
    top_level_entries = list(root.iterdir())
    if (
        len(top_level_entries) != 1
        or top_level_entries[0] != package_root
        or package_root.is_symlink()
        or not package_root.is_dir()
    ):
        raise InvalidPluginArchiveError("Archive must contain one unambiguous plugin package root")
    return package_root


def find_plugin_manifest_in_tree(root: Path) -> Path | None:
    """Find the sole plugin.toml in one unambiguous package root."""

    package_root = resolve_plugin_package_root(root)
    return package_root / "plugin.toml" if package_root is not None else None
