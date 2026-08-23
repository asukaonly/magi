"""Structured file/directory metadata tool.

Returns JSON-friendly metadata for a single path. Use this instead of
parsing the textual output of ``stat`` / ``dir`` / ``ls -l``.
"""
from __future__ import annotations

import mimetypes
import os
import stat as stat_mod
from typing import Any, Dict

from ..schema import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)
from ..utils.path_utils import resolve_path_from_workspace


def _kind_from_mode(mode: int, is_symlink: bool) -> str:
    if is_symlink:
        return "symlink"
    if stat_mod.S_ISDIR(mode):
        return "directory"
    if stat_mod.S_ISREG(mode):
        return "file"
    if stat_mod.S_ISFIFO(mode):
        return "fifo"
    if stat_mod.S_ISSOCK(mode):
        return "socket"
    return "other"


class FileInfoTool(Tool):
    """Return structured metadata for a single file or directory."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="file_info",
            description=(
                "Return structured metadata (size, kind, mtime, permissions, "
                "MIME type) for a single file or directory. Prefer this over "
                "parsing `stat` / `dir` / `ls -l` text output."
            ),
            category="file",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="path",
                    type=ParameterType.STRING,
                    description="Path to inspect",
                    required=True,
                ),
                ToolParameter(
                    name="follow_symlinks",
                    type=ParameterType.BOOLEAN,
                    description="Follow symbolic links when collecting stats",
                    required=False,
                    default=False,
                ),
            ],
            examples=[
                {
                    "input": {"path": "Z:/测试目录/notes.txt"},
                    "output": "Returns size, mtime, kind, mime for the file.",
                }
            ],
            timeout=5,
            retry_on_failure=False,
            dangerous=False,
            effect_replay_policy="read_only",
            tags=["file", "metadata", "structured"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        target_path = resolve_path_from_workspace(
            parameters.get("path"),
            workspace=context.workspace,
            default=".",
        )
        follow_symlinks = bool(parameters.get("follow_symlinks", False))

        if not os.path.lexists(target_path):
            return ToolResult(
                success=False,
                error=f"Path not found: {target_path}",
                error_code=ToolErrorCode.PATH_NOT_FOUND.value,
            )

        try:
            stat_result = os.stat(target_path, follow_symlinks=follow_symlinks)
        except PermissionError as exc:
            return ToolResult(
                success=False,
                error=f"Permission denied: {exc}",
                error_code=ToolErrorCode.PERMISSION_DENIED.value,
            )
        except OSError as exc:
            return ToolResult(
                success=False,
                error=str(exc),
                error_code=ToolErrorCode.READ_ERROR.value,
            )

        is_symlink = os.path.islink(target_path)
        kind = _kind_from_mode(stat_result.st_mode, is_symlink and not follow_symlinks)
        mime_type, _ = mimetypes.guess_type(target_path) if kind == "file" else (None, None)

        symlink_target: str | None = None
        if is_symlink:
            try:
                symlink_target = os.readlink(target_path)
            except OSError:
                symlink_target = None

        data: Dict[str, Any] = {
            "path": target_path,
            "name": os.path.basename(target_path) or target_path,
            "kind": kind,
            "is_dir": kind == "directory",
            "is_file": kind == "file",
            "is_symlink": is_symlink,
            "size": stat_result.st_size,
            "modified": stat_result.st_mtime,
            "accessed": stat_result.st_atime,
            "created": stat_result.st_ctime,
            "mode": stat_mod.filemode(stat_result.st_mode),
            "mode_octal": oct(stat_result.st_mode & 0o7777),
            "mime_type": mime_type,
            "symlink_target": symlink_target,
        }

        return ToolResult(success=True, data=data)
