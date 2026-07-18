"""Garbage collection for managed chat attachment assets."""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from pathlib import Path

from ..core.logger import get_logger
from ..core.sqlite import connect_sqlite
from ..utils.runtime import RuntimePaths, get_runtime_paths

logger = get_logger(__name__)


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

        files_deleted = 0
        dirs_deleted = 0
        for root_dir in self._asset_roots():
            result = self._remove_tree(
                root_dir / normalized_session_id,
                strict=True,
            )
            files_deleted += result["files_deleted"]
            dirs_deleted += result["dirs_deleted"]
        return {
            "chat_asset_files_deleted": files_deleted,
            "chat_asset_dirs_deleted": dirs_deleted,
        }

    def delete_message_assets(self, storage_rel_paths: list[str]) -> int:
        """Delete exact managed attachment files for one chat message.

        Missing files are already forgotten and therefore count as a successful
        retry.  An unsafe or undeletable path raises so the caller cannot report
        a completed user deletion while a managed copy remains on disk.
        """

        files_deleted = 0
        base_dir = self._runtime_paths.base_dir.resolve()
        resources_dir = self._runtime_paths.chat_resources_dir.resolve()
        for raw_path in storage_rel_paths:
            normalized = str(raw_path or "").strip()
            if not normalized:
                continue
            target = (base_dir / normalized).resolve()
            try:
                target.relative_to(resources_dir)
            except ValueError as exc:
                raise ChatAssetDeletionError(
                    "Attachment path is outside managed chat storage"
                ) from exc
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

    def delete_history_snapshot_assets(
        self,
        *,
        session_id: str,
        turn_ids: list[str],
        storage_rel_paths: list[str],
        delete_entire_session: bool,
    ) -> dict[str, int]:
        """Delete managed files owned by one immutable chat-history snapshot.

        A normal clear owns the complete current session and removes each
        session directory. Recovery may run after newer turns were added, so it
        removes exact attachment paths plus only the old turn directories.
        """

        normalized_session_id = self._normalize_session_id(session_id)
        if normalized_session_id is None:
            raise ValueError("Session ID is not safe for managed asset deletion")
        if delete_entire_session:
            return self.delete_session_assets(normalized_session_id)

        normalized_turn_ids: list[str] = []
        for raw_turn_id in turn_ids:
            normalized_turn_id = self._normalize_turn_id(raw_turn_id)
            if normalized_turn_id is None:
                raise ValueError("Turn ID is not safe for managed asset deletion")
            if normalized_turn_id not in normalized_turn_ids:
                normalized_turn_ids.append(normalized_turn_id)

        files_deleted = self.delete_message_assets(storage_rel_paths)
        dirs_deleted = 0
        for root_dir in self._asset_roots():
            for turn_id in normalized_turn_ids:
                result = self._remove_tree(
                    root_dir / normalized_session_id / turn_id,
                    strict=True,
                )
                files_deleted += result["files_deleted"]
                dirs_deleted += result["dirs_deleted"]
            self._remove_empty_asset_parents(
                root_dir / normalized_session_id,
                resources_dir=root_dir,
            )
        return {
            "chat_asset_files_deleted": files_deleted,
            "chat_asset_dirs_deleted": dirs_deleted,
        }

    def clear_all_assets(self) -> dict[str, int]:
        """Delete every managed chat asset directory under all chat asset roots."""

        files_deleted = 0
        dirs_deleted = 0
        for root_dir in self._asset_roots():
            if not root_dir.exists():
                continue
            for child in root_dir.iterdir():
                result = self._remove_tree(child)
                files_deleted += result["files_deleted"]
                dirs_deleted += result["dirs_deleted"]
        return {
            "chat_asset_files_deleted": files_deleted,
            "chat_asset_dirs_deleted": dirs_deleted,
        }

    def sweep_orphan_session_assets(self, *, orphan_grace_hours: int = 24) -> dict[str, int]:
        """Delete session asset directories with no active chat session row."""

        active_session_ids = self._active_session_ids()
        if active_session_ids is None:
            return {
                "chat_asset_orphan_sessions_deleted": 0,
                "chat_asset_orphan_files_deleted": 0,
                "chat_asset_orphan_dirs_deleted": 0,
            }
        cutoff = self._now() - (max(0, int(orphan_grace_hours)) * 3600)
        files_deleted = 0
        dirs_deleted = 0
        sessions_deleted = 0

        for root_dir in self._asset_roots():
            if not root_dir.exists():
                continue
            for child in root_dir.iterdir():
                if not child.is_dir() or child.name in active_session_ids:
                    continue
                if not self._is_older_than(child, cutoff):
                    continue
                result = self._remove_tree(child)
                if result["dirs_deleted"] > 0:
                    sessions_deleted += 1
                files_deleted += result["files_deleted"]
                dirs_deleted += result["dirs_deleted"]

        return {
            "chat_asset_orphan_sessions_deleted": sessions_deleted,
            "chat_asset_orphan_files_deleted": files_deleted,
            "chat_asset_orphan_dirs_deleted": dirs_deleted,
        }

    def _asset_roots(self) -> tuple[Path, Path, Path]:
        return (
            self._runtime_paths.chat_images_dir,
            self._runtime_paths.chat_files_dir,
            self._runtime_paths.chat_derived_dir,
        )

    def _active_session_ids(self) -> set[str] | None:
        chat_db_path = self._runtime_paths.chat_db_path
        if not chat_db_path.exists():
            return set()
        try:
            conn = connect_sqlite(chat_db_path, profile="mixed")
            rows = conn.execute(
                "SELECT session_id FROM chat_sessions WHERE deleted_at_ms IS NULL"
            ).fetchall()
            conn.close()
            return {str(row["session_id"]) for row in rows if row["session_id"] is not None}
        except Exception as exc:
            logger.warning(
                "chat_asset_gc.active_session_scan_failed", error=str(exc), exc_info=True
            )
            return None

    def _remove_tree(self, path: Path, *, strict: bool = False) -> dict[str, int]:
        try:
            resolved = path.resolve()
            resolved.relative_to(self._runtime_paths.chat_resources_dir.resolve())
        except Exception as exc:
            if strict:
                raise ChatAssetDeletionError(
                    "Managed chat asset path is outside chat storage"
                ) from exc
            return {"files_deleted": 0, "dirs_deleted": 0}

        try:
            if not path.exists():
                return {"files_deleted": 0, "dirs_deleted": 0}
            files_deleted, dirs_deleted = self._count_tree(path)
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except FileNotFoundError:
            return {"files_deleted": 0, "dirs_deleted": 0}
        except Exception as exc:
            if strict:
                raise ChatAssetDeletionError("Managed chat assets could not be deleted") from exc
            logger.warning(
                "chat_asset_gc.delete_failed", path=str(path), error=str(exc), exc_info=True
            )
            return {"files_deleted": 0, "dirs_deleted": 0}
        return {"files_deleted": files_deleted, "dirs_deleted": dirs_deleted}

    @staticmethod
    def _remove_empty_asset_parents(path: Path, *, resources_dir: Path) -> None:
        current = path
        while current != resources_dir:
            try:
                current.relative_to(resources_dir)
            except ValueError:
                return
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent

    @staticmethod
    def _count_tree(path: Path) -> tuple[int, int]:
        if not path.exists():
            return 0, 0
        if path.is_file():
            return 1, 0
        files = 0
        dirs = 1
        for child in path.rglob("*"):
            if child.is_file():
                files += 1
            elif child.is_dir():
                dirs += 1
        return files, dirs

    @staticmethod
    def _normalize_session_id(session_id: str) -> str | None:
        normalized = str(session_id or "").strip()
        if not normalized or "/" in normalized or "\\" in normalized:
            return None
        return normalized

    @staticmethod
    def _normalize_turn_id(turn_id: str) -> str | None:
        normalized = str(turn_id or "").strip()
        if not normalized or "/" in normalized or "\\" in normalized:
            return None
        return normalized

    @staticmethod
    def _is_older_than(path: Path, cutoff: float) -> bool:
        newest_mtime = path.stat().st_mtime
        if path.is_dir():
            for child in path.rglob("*"):
                try:
                    newest_mtime = max(newest_mtime, child.stat().st_mtime)
                except FileNotFoundError:
                    continue
        return newest_mtime < cutoff
