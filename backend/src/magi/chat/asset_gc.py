"""Garbage collection for managed chat attachment assets."""

from __future__ import annotations

import os
import shutil
import stat
import time
from collections.abc import Callable
from pathlib import Path

from ..core.logger import get_logger
from ..core.sqlite import connect_sqlite
from ..utils.runtime import RuntimePaths, get_runtime_paths
from magi.core.chat_assets.paths import (
    asset_scope_identity_key,
    is_safe_chat_asset_component,
    resolve_chat_asset_session_directory,
    resolve_chat_asset_turn_directory,
    verified_chat_asset_root,
    verified_chat_resources_dir,
)

logger = get_logger(__name__)

_MIN_UNOWNED_FILE_GRACE_HOURS = 25


class ChatAssetDeletionError(RuntimeError):
    """Raised when a user-requested managed asset deletion is incomplete."""


class ChatAssetGC:
    """Delete chat attachment and derived-resource files owned by Magi."""

    def __init__(
        self, *, runtime_paths: RuntimePaths | None = None, now: Callable[[], float] | None = None
    ) -> None:
        self._runtime_paths = runtime_paths or get_runtime_paths()
        self._now = now or time.time

    def delete_session_assets(self, session_id: str) -> dict[str, int]:
        """Delete all managed asset directories for one chat session."""

        normalized_session_id = self._normalize_session_id(session_id)
        if normalized_session_id is None:
            raise ValueError("Session ID is not safe for managed asset deletion")

        session_dirs: list[Path] = []
        for root_dir in self._asset_roots():
            try:
                session_dir = resolve_chat_asset_session_directory(
                    root_dir,
                    session_id=normalized_session_id,
                    runtime_paths=self._runtime_paths,
                )
            except ValueError as exc:
                raise ChatAssetDeletionError(
                    "Managed chat session asset scope is ambiguous"
                ) from exc
            if session_dir is not None:
                session_dirs.append(session_dir)

        files_deleted = 0
        dirs_deleted = 0
        for session_dir in session_dirs:
            result = self._remove_tree(
                session_dir,
                strict=True,
            )
            files_deleted += result["files_deleted"]
            dirs_deleted += result["dirs_deleted"]
        return {
            "chat_asset_files_deleted": files_deleted,
            "chat_asset_dirs_deleted": dirs_deleted,
        }

    def delete_message_assets(
        self,
        asset_references: list[tuple[str, str]],
    ) -> int:
        """Delete exact managed attachment files for one chat message.

        Missing files are already forgotten and therefore count as a successful
        retry.  An unsafe or undeletable path raises so the caller cannot report
        a completed user deletion while a managed copy remains on disk.
        """

        files_deleted = 0
        try:
            resources_dir = verified_chat_resources_dir(self._runtime_paths)
        except ValueError as exc:
            raise ChatAssetDeletionError(
                "Managed chat resources root was retargeted"
            ) from exc
        for raw_asset_key, raw_path in asset_references:
            expected_asset_key = str(raw_asset_key or "").strip()
            normalized = str(raw_path or "").strip()
            if not expected_asset_key or not normalized:
                continue
            try:
                target, current_asset_key, _ = self._managed_asset_entry(
                    Path(normalized)
                )
            except ValueError as exc:
                raise ChatAssetDeletionError(
                    "Attachment path is outside managed chat storage"
                ) from exc
            if current_asset_key != expected_asset_key:
                raise ChatAssetDeletionError(
                    "Managed chat attachment identity changed before deletion"
                )
            if target.is_symlink():
                try:
                    target.unlink()
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise ChatAssetDeletionError(
                        "Managed chat attachment could not be deleted"
                    ) from exc
                files_deleted += 1
                self._remove_empty_asset_parents(
                    target.parent,
                    resources_dir=resources_dir,
                )
                continue
            if not target.exists():
                continue
            if not target.is_file():
                raise ChatAssetDeletionError("Attachment path does not reference a file")
            try:
                target.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise ChatAssetDeletionError(
                    "Managed chat attachment could not be deleted"
                ) from exc
            files_deleted += 1
            self._remove_empty_asset_parents(target.parent, resources_dir=resources_dir)
        return files_deleted

    def list_snapshot_asset_references(
        self,
        *,
        session_id: str,
        turn_ids: list[str],
        delete_entire_session: bool,
    ) -> list[tuple[str, str]]:
        """List managed files inside the bounded directories of one snapshot."""

        normalized_session_id = self._normalize_session_id(session_id)
        if normalized_session_id is None:
            raise ValueError("Session ID is not safe for managed asset discovery")
        normalized_turn_ids: list[str] = []
        for raw_turn_id in turn_ids:
            normalized_turn_id = self._normalize_turn_id(raw_turn_id)
            if normalized_turn_id is None:
                raise ValueError("Turn ID is not safe for managed asset discovery")
            if normalized_turn_id not in normalized_turn_ids:
                normalized_turn_ids.append(normalized_turn_id)

        references: dict[str, str] = {}
        for root_dir in self._asset_roots():
            try:
                if delete_entire_session:
                    session_dir = resolve_chat_asset_session_directory(
                        root_dir,
                        session_id=normalized_session_id,
                        runtime_paths=self._runtime_paths,
                    )
                    candidate_dirs = [session_dir] if session_dir is not None else []
                else:
                    candidate_dirs = [
                        candidate_dir
                        for turn_id in normalized_turn_ids
                        if (
                            candidate_dir := resolve_chat_asset_turn_directory(
                                root_dir,
                                session_id=normalized_session_id,
                                turn_id=turn_id,
                                runtime_paths=self._runtime_paths,
                            )
                        )
                        is not None
                    ]
            except ValueError as exc:
                raise ChatAssetDeletionError(
                    "Managed chat snapshot directory identity changed"
                ) from exc
            for candidate_dir in candidate_dirs:
                candidates = self._list_tree_entries_without_following_symlinks(
                    candidate_dir
                )
                if candidates is None:
                    raise ChatAssetDeletionError(
                        "Managed chat snapshot directory could not be inspected safely"
                    )
                for candidate in candidates:
                    try:
                        _, asset_key, storage_rel_path = self._managed_asset_entry(
                            candidate
                        )
                    except ValueError as exc:
                        raise ChatAssetDeletionError(
                            "Managed chat asset path is outside chat storage"
                        ) from exc
                    references.setdefault(asset_key, storage_rel_path)
        return sorted(references.items())

    def clear_all_assets(self) -> dict[str, int]:
        """Delete every managed chat asset directory under all chat asset roots."""

        files_deleted = 0
        dirs_deleted = 0
        for root_dir in self._asset_roots():
            if not root_dir.exists():
                continue
            for child in root_dir.iterdir():
                result = self._remove_tree(child, strict=True)
                files_deleted += result["files_deleted"]
                dirs_deleted += result["dirs_deleted"]
        return {
            "chat_asset_files_deleted": files_deleted,
            "chat_asset_dirs_deleted": dirs_deleted,
        }

    def sweep_orphan_assets(
        self,
        *,
        orphan_grace_hours: int = 24,
        delete_orphan_sessions: bool = True,
    ) -> dict[str, int]:
        """Delete old unowned files and optionally remove orphan session scopes."""

        active_asset_scopes = self._active_asset_scopes()
        if active_asset_scopes is None:
            return {
                "chat_asset_orphan_sessions_deleted": 0,
                "chat_asset_orphan_files_deleted": 0,
                "chat_asset_orphan_dirs_deleted": 0,
            }
        (
            active_session_ids,
            owned_asset_keys,
            owned_scope_identity_keys,
        ) = active_asset_scopes
        active_session_ids_by_identity: dict[str, set[str]] = {}
        for session_id in active_session_ids:
            active_session_ids_by_identity.setdefault(
                asset_scope_identity_key(session_id),
                set(),
            ).add(session_id)
        configured_grace_hours = max(0, int(orphan_grace_hours))
        orphan_session_cutoff = self._now() - (configured_grace_hours * 3600)
        unowned_file_cutoff = self._now() - (
            max(configured_grace_hours, _MIN_UNOWNED_FILE_GRACE_HOURS) * 3600
        )
        files_deleted = 0
        dirs_deleted = 0
        deleted_session_identity_keys: set[str] = set()

        try:
            asset_roots = self._asset_roots()
        except ChatAssetDeletionError as exc:
            logger.warning(
                "chat_asset_gc.asset_root_scan_failed",
                error=str(exc),
                exc_info=True,
            )
            return {
                "chat_asset_orphan_sessions_deleted": 0,
                "chat_asset_orphan_files_deleted": 0,
                "chat_asset_orphan_dirs_deleted": 0,
            }
        for root_dir in asset_roots:
            if not self._is_real_directory(root_dir):
                continue
            session_entries_by_identity = self._scope_entries_by_identity(
                root_dir,
                scope_kind="session",
            )
            if session_entries_by_identity is None:
                continue
            owned_session_identity_keys = owned_scope_identity_keys.get(
                root_dir.name,
                set(),
            )
            for session_identity_key, session_entries in session_entries_by_identity.items():
                if len(session_entries) != 1:
                    logger.warning(
                        "chat_asset_gc.ambiguous_session_scope_skipped",
                        root=str(root_dir),
                        identity_key=session_identity_key,
                        entries=sorted(entry.name for entry in session_entries),
                    )
                    continue
                session_entry = session_entries[0]
                entry_mode = self._lstat_mode(session_entry)
                if entry_mode is None:
                    continue
                active_spellings = active_session_ids_by_identity.get(
                    session_identity_key,
                    set(),
                )
                if active_spellings:
                    if (
                        len(active_spellings) != 1
                        or session_entry.name not in active_spellings
                        or not stat.S_ISDIR(entry_mode)
                        or not is_safe_chat_asset_component(session_entry.name)
                    ):
                        continue
                    unowned_result = self._sweep_unowned_active_session_files(
                        root_dir=root_dir,
                        session_dir=session_entry,
                        owned_asset_keys=owned_asset_keys,
                        cutoff=unowned_file_cutoff,
                    )
                    files_deleted += unowned_result["files_deleted"]
                    dirs_deleted += unowned_result["dirs_deleted"]
                    continue
                if session_identity_key in owned_session_identity_keys:
                    continue
                if not delete_orphan_sessions:
                    continue
                if not (
                    stat.S_ISDIR(entry_mode)
                    or stat.S_ISLNK(entry_mode)
                ):
                    continue
                if not self._is_older_than(session_entry, orphan_session_cutoff):
                    continue
                result = self._remove_tree(session_entry)
                if result["dirs_deleted"] > 0:
                    deleted_session_identity_keys.add(session_identity_key)
                files_deleted += result["files_deleted"]
                dirs_deleted += result["dirs_deleted"]

        return {
            "chat_asset_orphan_sessions_deleted": len(
                deleted_session_identity_keys
            ),
            "chat_asset_orphan_files_deleted": files_deleted,
            "chat_asset_orphan_dirs_deleted": dirs_deleted,
        }

    def _asset_roots(self) -> tuple[Path, Path, Path]:
        try:
            return tuple(
                verified_chat_asset_root(root_dir, self._runtime_paths)
                for root_dir in (
                    self._runtime_paths.chat_images_dir,
                    self._runtime_paths.chat_files_dir,
                    self._runtime_paths.chat_derived_dir,
                )
            )
        except ValueError as exc:
            raise ChatAssetDeletionError(
                "Managed chat asset root was retargeted"
            ) from exc

    def _managed_asset_entry(self, raw_path: Path) -> tuple[Path, str, str]:
        base_dir = self._runtime_paths.base_dir.resolve()
        resources_dir = verified_chat_resources_dir(self._runtime_paths)
        candidate = raw_path if raw_path.is_absolute() else base_dir / raw_path
        if candidate.name in {"", ".", ".."}:
            raise ValueError("Managed chat asset path is not a file entry")
        try:
            parent = candidate.parent.resolve()
            relative_parent = parent.relative_to(resources_dir)
            if len(relative_parent.parts) != 3:
                raise ValueError("Managed chat asset path has an invalid scope")
            root_name, session_id, turn_id = relative_parent.parts
            root_dir = {
                "images": self._runtime_paths.chat_images_dir,
                "files": self._runtime_paths.chat_files_dir,
                "derived": self._runtime_paths.chat_derived_dir,
            }.get(root_name)
            if root_dir is None:
                raise ValueError("Managed chat asset path has an invalid root")
            expected_parent = resolve_chat_asset_turn_directory(
                root_dir,
                session_id=session_id,
                turn_id=turn_id,
                runtime_paths=self._runtime_paths,
            )
            target = parent / candidate.name
            if expected_parent is None:
                if target.exists() or target.is_symlink():
                    raise ValueError(
                        "Managed chat asset path has an invalid scope"
                    )
            elif expected_parent != parent:
                raise ValueError("Managed chat asset path has an invalid scope")
            asset_key = target.relative_to(resources_dir).as_posix()
            storage_rel_path = target.relative_to(base_dir).as_posix()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError("Managed chat asset path is outside chat storage") from exc
        return target, asset_key, storage_rel_path

    def _active_asset_scopes(
        self,
    ) -> tuple[set[str], set[str], dict[str, set[str]]] | None:
        chat_db_path = self._runtime_paths.chat_db_path
        if not chat_db_path.exists():
            logger.warning(
                "chat_asset_gc.chat_database_missing",
                path=str(chat_db_path),
            )
            return None
        conn = None
        try:
            conn = connect_sqlite(chat_db_path, profile="mixed")
            conn.execute("BEGIN")
            session_rows = conn.execute(
                "SELECT session_id FROM chat_sessions WHERE deleted_at_ms IS NULL"
            ).fetchall()
            owner_rows = conn.execute(
                """
                SELECT DISTINCT refs.asset_key
                FROM chat_message_asset_refs AS refs
                JOIN chat_messages AS owner_message
                  ON owner_message.message_id = refs.message_id
                JOIN chat_sessions AS owner_session
                  ON owner_session.session_id = owner_message.session_id
                WHERE owner_session.deleted_at_ms IS NULL
                """
            ).fetchall()
            active_session_ids = {
                str(row["session_id"])
                for row in session_rows
                if row["session_id"] is not None
            }
            owned_asset_keys: set[str] = set()
            owned_scope_identity_keys: dict[str, set[str]] = {}
            for row in owner_rows:
                asset_key = str(row["asset_key"] or "").strip()
                parts = asset_key.split("/")
                if len(parts) != 4:
                    continue
                root_name, session_id, turn_id, file_name = parts
                if (
                    root_name not in {"images", "files", "derived"}
                    or not is_safe_chat_asset_component(session_id)
                    or not is_safe_chat_asset_component(turn_id)
                    or not file_name
                ):
                    continue
                owned_asset_keys.add(asset_key)
                owned_scope_identity_keys.setdefault(root_name, set()).add(
                    asset_scope_identity_key(session_id)
                )
            return active_session_ids, owned_asset_keys, owned_scope_identity_keys
        except Exception as exc:
            logger.warning(
                "chat_asset_gc.active_scope_scan_failed", error=str(exc), exc_info=True
            )
            return None
        finally:
            if conn is not None:
                conn.close()

    def _sweep_unowned_active_session_files(
        self,
        *,
        root_dir: Path,
        session_dir: Path,
        owned_asset_keys: set[str],
        cutoff: float,
    ) -> dict[str, int]:
        files_deleted = 0
        dirs_deleted = 0
        if not self._is_real_directory(session_dir, expected_parent=root_dir):
            return {
                "files_deleted": files_deleted,
                "dirs_deleted": dirs_deleted,
            }
        turn_entries_by_identity = self._scope_entries_by_identity(
            session_dir,
            scope_kind="turn",
        )
        if turn_entries_by_identity is None:
            return {
                "files_deleted": files_deleted,
                "dirs_deleted": dirs_deleted,
            }
        for turn_identity_key, turn_entries in turn_entries_by_identity.items():
            if len(turn_entries) != 1:
                logger.warning(
                    "chat_asset_gc.ambiguous_turn_scope_skipped",
                    root=str(root_dir),
                    session_id=session_dir.name,
                    identity_key=turn_identity_key,
                    entries=sorted(entry.name for entry in turn_entries),
                )
                continue
            turn_dir = turn_entries[0]
            if (
                not is_safe_chat_asset_component(turn_dir.name)
                or not self._is_real_directory(
                    turn_dir,
                    expected_parent=session_dir,
                )
            ):
                continue
            try:
                file_entries = tuple(turn_dir.iterdir())
            except OSError as exc:
                logger.warning(
                    "chat_asset_gc.active_turn_files_scan_failed",
                    root=str(root_dir),
                    session_id=session_dir.name,
                    turn_id=turn_dir.name,
                    error=str(exc),
                )
                continue
            for candidate in file_entries:
                candidate_mode = self._lstat_mode(candidate)
                if candidate_mode is None or not (
                    stat.S_ISREG(candidate_mode)
                    or stat.S_ISLNK(candidate_mode)
                ):
                    continue
                try:
                    target, asset_key = self._indexed_asset_entry(
                        candidate,
                        root_dir=root_dir,
                        session_dir=session_dir,
                        turn_dir=turn_dir,
                    )
                except ValueError as exc:
                    logger.warning(
                        "chat_asset_gc.active_file_scope_scan_failed",
                        path=str(candidate),
                        error=str(exc),
                    )
                    continue
                if asset_key in owned_asset_keys or not self._is_file_older_than(
                    target,
                    cutoff,
                ):
                    continue
                if (
                    not self._is_real_directory(
                        session_dir,
                        expected_parent=root_dir,
                    )
                    or not self._is_real_directory(
                        turn_dir,
                        expected_parent=session_dir,
                    )
                ):
                    continue
                refreshed_mode = self._lstat_mode(target)
                if refreshed_mode is None or not (
                    stat.S_ISREG(refreshed_mode)
                    or stat.S_ISLNK(refreshed_mode)
                ):
                    continue
                try:
                    target.unlink()
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    logger.warning(
                        "chat_asset_gc.delete_failed",
                        path=str(target),
                        error=str(exc),
                        exc_info=True,
                    )
                    continue
                files_deleted += 1
                dirs_deleted += self._remove_empty_asset_parents(
                    target.parent,
                    resources_dir=root_dir,
                )
        return {
            "files_deleted": files_deleted,
            "dirs_deleted": dirs_deleted,
        }

    def _indexed_asset_entry(
        self,
        candidate: Path,
        *,
        root_dir: Path,
        session_dir: Path,
        turn_dir: Path,
    ) -> tuple[Path, str]:
        """Build one asset identity from already verified directory scopes."""

        resources_dir = verified_chat_resources_dir(self._runtime_paths)
        if (
            candidate.parent != turn_dir
            or turn_dir.parent != session_dir
            or session_dir.parent != root_dir
        ):
            raise ValueError("Managed chat asset path has an invalid scope")
        try:
            asset_key = candidate.relative_to(resources_dir).as_posix()
        except ValueError as exc:
            raise ValueError(
                "Managed chat asset path is outside chat storage"
            ) from exc
        if len(asset_key.split("/")) != 4:
            raise ValueError("Managed chat asset path has an invalid scope")
        return candidate, asset_key

    @classmethod
    def _scope_entries_by_identity(
        cls,
        parent: Path,
        *,
        scope_kind: str,
    ) -> dict[str, list[Path]] | None:
        """Enumerate one scope level once and group conservative aliases."""

        if not cls._is_real_directory(parent):
            return None
        try:
            entries = tuple(parent.iterdir())
        except OSError as exc:
            logger.warning(
                "chat_asset_gc.scope_scan_failed",
                path=str(parent),
                scope_kind=scope_kind,
                error=str(exc),
            )
            return None
        grouped: dict[str, list[Path]] = {}
        for entry in entries:
            grouped.setdefault(
                asset_scope_identity_key(entry.name),
                [],
            ).append(entry)
        return grouped

    @staticmethod
    def _lstat_mode(path: Path) -> int | None:
        try:
            return path.lstat().st_mode
        except OSError:
            return None

    @classmethod
    def _is_real_directory(
        cls,
        path: Path,
        *,
        expected_parent: Path | None = None,
    ) -> bool:
        mode = cls._lstat_mode(path)
        if mode is None or not stat.S_ISDIR(mode):
            return False
        if expected_parent is not None and path.parent != expected_parent:
            return False
        try:
            return path.resolve() == path
        except (OSError, RuntimeError):
            return False

    def _remove_tree(self, path: Path, *, strict: bool = False) -> dict[str, int]:
        try:
            resources_dir = verified_chat_resources_dir(self._runtime_paths)
            parent = path.parent.resolve()
            parent.relative_to(resources_dir)
            target = parent / path.name
        except Exception as exc:
            if strict:
                raise ChatAssetDeletionError(
                    "Managed chat asset path is outside chat storage"
                ) from exc
            return {"files_deleted": 0, "dirs_deleted": 0}

        try:
            if target.is_symlink():
                target.unlink()
                return {"files_deleted": 1, "dirs_deleted": 0}
            resolved = target.resolve()
            resolved.relative_to(resources_dir)
            if not target.exists():
                return {"files_deleted": 0, "dirs_deleted": 0}
            tree_counts = self._count_tree(target)
            if tree_counts is None:
                raise OSError("Managed chat asset tree could not be inspected safely")
            files_deleted, dirs_deleted = tree_counts
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        except FileNotFoundError:
            return {"files_deleted": 0, "dirs_deleted": 0}
        except Exception as exc:
            if strict:
                raise ChatAssetDeletionError("Managed chat assets could not be deleted") from exc
            logger.warning(
                "chat_asset_gc.delete_failed",
                path=str(target),
                error=str(exc),
                exc_info=True,
            )
            return {"files_deleted": 0, "dirs_deleted": 0}
        return {"files_deleted": files_deleted, "dirs_deleted": dirs_deleted}

    @staticmethod
    def _remove_empty_asset_parents(path: Path, *, resources_dir: Path) -> int:
        current = path
        dirs_deleted = 0
        while current != resources_dir:
            try:
                current.relative_to(resources_dir)
            except ValueError:
                return dirs_deleted
            try:
                current.rmdir()
            except OSError:
                return dirs_deleted
            dirs_deleted += 1
            current = current.parent
        return dirs_deleted

    @classmethod
    def _count_tree(cls, path: Path) -> tuple[int, int] | None:
        scanned = cls._scan_tree_without_following_symlinks(path)
        if scanned is None:
            return None
        _, files, dirs = scanned
        return files, dirs

    @staticmethod
    def _normalize_session_id(session_id: str) -> str | None:
        normalized = str(session_id or "").strip()
        if not is_safe_chat_asset_component(normalized):
            return None
        return normalized

    @staticmethod
    def _normalize_turn_id(turn_id: str) -> str | None:
        normalized = str(turn_id or "").strip()
        if not is_safe_chat_asset_component(normalized):
            return None
        return normalized

    @classmethod
    def _is_older_than(cls, path: Path, cutoff: float) -> bool:
        scanned = cls._scan_tree_without_following_symlinks(path)
        if scanned is None:
            return False
        newest_mtime, _, _ = scanned
        return newest_mtime < cutoff

    @staticmethod
    def _is_file_older_than(path: Path, cutoff: float) -> bool:
        try:
            return path.lstat().st_mtime < cutoff
        except OSError:
            return False

    @classmethod
    def _scan_tree_without_following_symlinks(
        cls,
        path: Path,
    ) -> tuple[float, int, int] | None:
        """Return newest mtime and entry counts without crossing symlinks."""

        try:
            root_stat = path.lstat()
        except OSError:
            return None
        newest_mtime = root_stat.st_mtime
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            return newest_mtime, 1, 0
        if not cls._is_real_directory(path):
            return None

        files = 0
        dirs = 1
        pending = [path]
        while pending:
            current = pending.pop()
            if not cls._is_real_directory(current):
                return None
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            entry_stat = entry.stat(follow_symlinks=False)
                        except OSError:
                            return None
                        newest_mtime = max(newest_mtime, entry_stat.st_mtime)
                        if stat.S_ISDIR(entry_stat.st_mode):
                            dirs += 1
                            pending.append(Path(entry.path))
                        else:
                            files += 1
            except OSError:
                return None
        return newest_mtime, files, dirs

    @classmethod
    def _list_tree_entries_without_following_symlinks(
        cls,
        path: Path,
    ) -> tuple[Path, ...] | None:
        """List removable file entries without traversing directory symlinks."""

        try:
            root_stat = path.lstat()
        except OSError:
            return None
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or not cls._is_real_directory(path)
        ):
            return None

        file_entries: list[Path] = []
        pending = [path]
        while pending:
            current = pending.pop()
            if not cls._is_real_directory(current):
                return None
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            entry_stat = entry.stat(follow_symlinks=False)
                        except OSError:
                            return None
                        entry_path = Path(entry.path)
                        if stat.S_ISDIR(entry_stat.st_mode):
                            pending.append(entry_path)
                        elif (
                            stat.S_ISREG(entry_stat.st_mode)
                            or stat.S_ISLNK(entry_stat.st_mode)
                        ):
                            file_entries.append(entry_path)
            except OSError:
                return None
        return tuple(file_entries)
