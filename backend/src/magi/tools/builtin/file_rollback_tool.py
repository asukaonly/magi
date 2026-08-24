"""file_rollback - undo recent file_edit / file_write mutations."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

from magi_plugin_sdk.workspace_cache import (
    EditOp,
    EditRecord,
    SessionCache,
    SnapshotRef,
    resolve_session_cache,
)
from magi_plugin_sdk.fs import atomic_write_bytes
from ...core.logger import get_logger
from ..schema import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)

logger = get_logger(__name__)


class FileRollbackTool(Tool):
    """Restore prior file content recorded by ``file_edit`` / ``file_write``."""

    MODE_LAST = "last"
    MODE_ALL = "all"
    MODE_PATH = "path"
    _MODES = (MODE_LAST, MODE_ALL, MODE_PATH)

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="file_rollback",
            description=(
                "Undo recent file mutations recorded by file_edit and "
                "file_write. mode=last undoes the most recent edit; "
                "mode=all undoes every edit in this session in reverse "
                "order; mode=path undoes the most recent edit for a given "
                "path. Pass dry_run=true to preview without changing disk."
            ),
            category="file",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="mode",
                    type=ParameterType.STRING,
                    description="One of: last, all, path",
                    required=False,
                    default="last",
                    enum=list(FileRollbackTool._MODES),
                ),
                ToolParameter(
                    name="path",
                    type=ParameterType.STRING,
                    description="File path to roll back. Required when mode=path.",
                    required=False,
                ),
                ToolParameter(
                    name="dry_run",
                    type=ParameterType.BOOLEAN,
                    description="If true, report what would be restored without changing disk.",
                    required=False,
                    default=False,
                ),
            ],
            timeout=10,
            retry_on_failure=False,
            dangerous=True,
            effect_class="local_write",
            effect_replay_policy="reconcilable",
            tags=["file", "rollback"],
            metadata={
                "task_intents": ["recover_state"],
                "domains": ["codebase", "config"],
                "operations": ["restore"],
                "requires_known_target": False,
                "cost": "low",
                "tool_hint": (
                    "Use after a file_edit or file_write that produced an "
                    "unwanted change. Default mode=last is enough for a "
                    "simple undo; pass mode=path with the original path "
                    "to undo a specific file's last edit while leaving "
                    "others intact."
                ),
            },
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        mode = str(parameters.get("mode") or "last").strip()
        path_param = parameters.get("path")
        dry_run = bool(parameters.get("dry_run", False))

        if mode not in self._MODES:
            return ToolResult(
                success=False,
                error=f"Unknown mode {mode!r}; must be one of {self._MODES}",
                error_code=ToolErrorCode.INVALID_MODE.value,
            )

        sid = str((context.env_vars or {}).get("session_id") or "").strip()
        if not sid:
            return ToolResult(
                success=False,
                error="file_rollback requires an active session",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        if mode == self.MODE_PATH and not path_param:
            return ToolResult(
                success=False,
                error="mode=path requires the path parameter",
                error_code=ToolErrorCode.MISSING_PATH.value,
            )

        try:
            sc = resolve_session_cache(context.workspace, sid)
        except Exception as exc:
            logger.warning("file_rollback.cache_init_failed", exc_info=True)
            return ToolResult(
                success=False,
                error=f"Failed to open session cache: {exc}",
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
            )

        edits = list(sc.iter_edits())
        targets = self._select_targets(edits, mode, path_param, sc)

        restored: list[dict[str, Any]] = []
        for rec in targets:
            entry = self._restore_one(sc, rec, dry_run=dry_run)
            restored.append(entry)
            if not entry["ok"] and not dry_run:
                break

        return ToolResult(
            success=True,
            data={
                "mode": mode,
                "dry_run": dry_run,
                "restored": restored,
            },
        )

    def _select_targets(
        self,
        edits: list[EditRecord],
        mode: str,
        path_param: Any,
        sc: SessionCache,
    ) -> list[EditRecord]:
        if not edits:
            return []
        if mode == self.MODE_LAST:
            return [edits[-1]]
        if mode == self.MODE_ALL:
            return list(reversed(edits))
        if mode == self.MODE_PATH:
            try:
                rel = self._relative_to_workspace(sc, str(path_param))
            except ValueError:
                return []
            for rec in reversed(edits):
                if rec.path == rel:
                    return [rec]
            return []
        return []

    @staticmethod
    def _relative_to_workspace(sc: SessionCache, file_path: str) -> str:
        return (
            Path(file_path).resolve().relative_to(sc.root.workspace_root.resolve()).as_posix()
        )

    def _restore_one(
        self,
        sc: SessionCache,
        rec: EditRecord,
        *,
        dry_run: bool,
    ) -> dict[str, Any]:
        absolute = sc.root.workspace_root / rec.path
        try:
            snapshot_bytes = sc.read_snapshot(SnapshotRef(sha256=rec.snapshot_ref))
        except Exception as exc:
            logger.warning("file_rollback.snapshot_read_failed", exc_info=True)
            return {
                "path": rec.path,
                "ok": False,
                "error": f"snapshot unreadable: {exc}",
                "before_op": rec.op,
            }
        if dry_run:
            return {
                "path": rec.path,
                "ok": True,
                "would_restore_bytes": len(snapshot_bytes),
                "before_op": rec.op,
            }
        try:
            current = absolute.read_bytes() if absolute.is_file() else b""
            atomic_write_bytes(absolute, snapshot_bytes)
        except Exception as exc:
            logger.warning("file_rollback.write_failed", exc_info=True)
            return {
                "path": rec.path,
                "ok": False,
                "error": str(exc),
                "before_op": rec.op,
            }
        try:
            inverse_op: EditOp = "replace" if rec.op == "replace" else "write"
            sha_before = hashlib.sha256(current).hexdigest()
            new_ref = sc.write_snapshot(current)
            sc.record_edit(
                path=str(absolute),
                op=inverse_op,
                sha256_before=sha_before,
                sha256_after=hashlib.sha256(snapshot_bytes).hexdigest(),
                snapshot_ref=new_ref.sha256,
            )
        except Exception:
            logger.warning("file_rollback.audit_failed", exc_info=True)
        return {
            "path": rec.path,
            "ok": True,
            "restored_bytes": len(snapshot_bytes),
            "before_op": rec.op,
        }


__all__ = ["FileRollbackTool"]
