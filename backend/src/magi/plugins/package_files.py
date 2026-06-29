"""Filesystem operations for plugin package archives and install directories."""

from __future__ import annotations

from collections.abc import Callable
import gzip
import logging
from pathlib import Path
import shutil
import tarfile
import tempfile
import uuid
import zipfile

logger = logging.getLogger(__name__)


class InvalidPluginArchiveError(ValueError):
    """Raised when an uploaded plugin archive is unsupported, corrupt, or unsafe."""


def user_plugins_root() -> Path:
    return Path("~/.magi/plugins").expanduser()


def replace_plugin_directory(
    source_dir: Path,
    dest_dir: Path,
    *,
    prepare_staging_dir: Callable[[Path], None] | None = None,
    before_swap: Callable[[], None] | None = None,
) -> None:
    """Stage plugin files on disk before swapping them into place."""

    parent_dir = dest_dir.parent
    parent_dir.mkdir(parents=True, exist_ok=True)

    staging_dir = Path(tempfile.mkdtemp(prefix=f".{dest_dir.name}-staging-", dir=parent_dir))
    backup_dir = parent_dir / f".{dest_dir.name}-backup-{uuid.uuid4().hex}"

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

        if before_swap is not None:
            before_swap()

        if dest_dir.exists():
            logger.info(
                "Backing up existing plugin directory",
                extra={"dest_dir": str(dest_dir), "backup_dir": str(backup_dir)},
            )
            dest_dir.replace(backup_dir)

        try:
            staging_dir.replace(dest_dir)
            logger.info(
                "Promoted staged plugin directory",
                extra={"dest_dir": str(dest_dir), "staging_dir": str(staging_dir)},
            )
        except Exception:
            if backup_dir.exists() and not dest_dir.exists():
                backup_dir.replace(dest_dir)
            raise
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)


def extract_plugin_archive(archive_path: Path, dest: Path) -> None:
    """Extract a plugin archive into *dest* and reject unsafe paths."""

    name = archive_path.name.lower()
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        try:
            with tarfile.open(archive_path, "r:gz") as tf:
                for member in tf.getmembers():
                    if member.name.startswith("/") or ".." in member.name.split("/"):
                        raise InvalidPluginArchiveError(f"Unsafe path in archive: {member.name}")
                tf.extractall(dest)
        except (tarfile.TarError, gzip.BadGzipFile, EOFError) as exc:
            raise InvalidPluginArchiveError(f"Not a valid .tar.gz archive: {exc}") from exc
        return

    if name.endswith(".zip"):
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                for info in zf.infolist():
                    if info.filename.startswith("/") or ".." in info.filename.split("/"):
                        raise InvalidPluginArchiveError(f"Unsafe path in archive: {info.filename}")
                    extracted_str = zf.extract(info, dest)
                    if not info.is_dir():
                        mode = (info.external_attr >> 16) & 0o777
                        if mode:
                            Path(extracted_str).chmod(mode)
        except zipfile.BadZipFile as exc:
            raise InvalidPluginArchiveError(f"Not a valid .zip archive: {exc}") from exc
        return

    raise InvalidPluginArchiveError(f"Unsupported archive format: {archive_path.name}")


def find_plugin_manifest_in_tree(root: Path) -> Path | None:
    """Find plugin.toml at root level or one directory deep."""

    direct = root / "plugin.toml"
    if direct.exists():
        return direct
    for child in root.iterdir():
        if child.is_dir():
            candidate = child / "plugin.toml"
            if candidate.exists():
                return candidate
    return None
