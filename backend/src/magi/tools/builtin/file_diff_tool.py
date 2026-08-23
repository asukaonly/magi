"""file_diff - render unified diff between snapshot bytes and current disk."""
from __future__ import annotations

import difflib
import hashlib
from pathlib import Path
from typing import Any, Dict

from magi_plugin_sdk.workspace_cache import (
    EditRecord,
    SessionCache,
    SnapshotRef,
    resolve_session_cache,
)
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

_BINARY_MARKER = "[binary diff suppressed]"


class FileDiffTool(Tool):
    """Render unified diffs against snapshots stored by file_edit / file_write."""

    MODE_LAST = "last"
    MODE_ALL = "all"
    MODE_PATH = "path"
    _MODES = (MODE_LAST, MODE_ALL, MODE_PATH)

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="file_diff",
            description=(
                "Show what changed between a recorded edit's snapshot and the "
                "current on-disk content. mode=last diffs the most recent edit; "
                "mode=all returns every edit's diff in reverse chronological "
                "order; mode=path diffs the most recent edit for a given path. "
                "Output is plain unified-diff text plus a small structured summary."
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
                    enum=list(FileDiffTool._MODES),
                ),
                ToolParameter(
                    name="path",
                    type=ParameterType.STRING,
                    description="File path. Required when mode=path.",
                    required=False,
                ),
            ],
            timeout=10,
            retry_on_failure=False,
            dangerous=False,
            effect_replay_policy="read_only",
            tags=["file", "diff"],
            metadata={
                "task_intents": ["inspect_change"],
                "domains": ["codebase", "config"],
                "operations": ["inspect"],
                "requires_known_target": False,
                "cost": "low",
                "tool_hint": (
                    "Use after a file_edit or file_write to confirm exactly what "
                    "changed, or before a file_rollback to preview what would be "
                    "undone."
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
                error="file_diff requires an active session",
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
            logger.warning("file_diff.cache_init_failed", exc_info=True)
            return ToolResult(
                success=False,
                error=f"Failed to open session cache: {exc}",
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
            )

        edits = list(sc.iter_edits())
        targets = self._select_targets(edits, mode, path_param, sc)

        diffs = [self._render_one(sc, rec) for rec in targets]

        return ToolResult(
            success=True,
            data={
                "mode": mode,
                "diffs": diffs,
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
                rel = (
                    Path(str(path_param))
                    .resolve()
                    .relative_to(sc.root.workspace_root.resolve())
                    .as_posix()
                )
            except ValueError:
                return []
            for rec in reversed(edits):
                if rec.path == rel:
                    return [rec]
            return []
        return []

    def _render_one(self, sc: SessionCache, rec: EditRecord) -> dict[str, Any]:
        absolute = sc.root.workspace_root / rec.path
        try:
            before_bytes = sc.read_snapshot(SnapshotRef(sha256=rec.snapshot_ref))
        except Exception as exc:
            logger.warning("file_diff.snapshot_read_failed", exc_info=True)
            return {
                "path": rec.path,
                "ok": False,
                "error": f"snapshot unreadable: {exc}",
                "diff_text": "",
                "binary": False,
                "recorded_sha256_after": rec.sha256_after,
                "current_sha256": "",
            }
        try:
            after_bytes = absolute.read_bytes() if absolute.is_file() else b""
        except Exception:
            logger.warning("file_diff.current_read_failed", exc_info=True)
            after_bytes = b""

        current_sha = hashlib.sha256(after_bytes).hexdigest()
        binary, diff_text = self._compute_diff(rec.path, before_bytes, after_bytes)
        return {
            "path": rec.path,
            "ok": True,
            "binary": binary,
            "diff_text": diff_text,
            "recorded_sha256_after": rec.sha256_after,
            "current_sha256": current_sha,
            "op": rec.op,
        }

    @staticmethod
    def _compute_diff(rel_path: str, before: bytes, after: bytes) -> tuple[bool, str]:
        try:
            before_text = before.decode("utf-8")
            after_text = after.decode("utf-8")
        except UnicodeDecodeError:
            return True, _BINARY_MARKER
        diff_lines = difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
        )
        return False, "".join(diff_lines)


__all__ = ["FileDiffTool"]
