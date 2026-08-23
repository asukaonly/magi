"""Structured directory listing tool.

Returns JSON-friendly metadata for the entries of a directory using
``os.scandir`` so that file names round-trip cleanly through Unicode and
no shell text parsing is required. Prefer this over ``bash dir`` /
``bash ls`` for any agent workflow that needs to enumerate files.
"""

from __future__ import annotations

import os
import stat as stat_mod
from dataclasses import dataclass
from typing import Any, Dict, List

from ..schema import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)
from ..utils.batch_autodetect import suggest_batch
from ..utils.path_utils import (
    DEFAULT_EXCLUDE_PATTERNS,
    has_hidden_path_component,
    matches_exclude_path,
    normalize_exclude_patterns,
    resolve_path_from_workspace,
)

_SORT_KEYS = {"name", "size", "modified", "type"}


@dataclass(frozen=True)
class _FileListRequest:
    target_path: str
    recursive: bool
    include_hidden: bool
    max_depth: int
    max_entries: int
    exclude_patterns: list[str]
    sort_by: str


def _entry_kind(entry_stat: os.stat_result, is_symlink: bool) -> str:
    if is_symlink:
        return "symlink"
    mode = entry_stat.st_mode
    if stat_mod.S_ISDIR(mode):
        return "directory"
    if stat_mod.S_ISREG(mode):
        return "file"
    if stat_mod.S_ISFIFO(mode):
        return "fifo"
    if stat_mod.S_ISSOCK(mode):
        return "socket"
    return "other"


def _file_list_parameters() -> list[ToolParameter]:
    return [
        ToolParameter(
            name="path",
            type=ParameterType.STRING,
            description="Directory to list",
            required=False,
            default=".",
        ),
        ToolParameter(
            name="recursive",
            type=ParameterType.BOOLEAN,
            description="Recurse into subdirectories",
            required=False,
            default=False,
        ),
        ToolParameter(
            name="include_hidden",
            type=ParameterType.BOOLEAN,
            description="Include entries whose name starts with '.'",
            required=False,
            default=False,
        ),
        ToolParameter(
            name="max_depth",
            type=ParameterType.INTEGER,
            description="Maximum recursion depth (only when recursive=True)",
            required=False,
            default=8,
            min_value=1,
            max_value=64,
        ),
        ToolParameter(
            name="max_entries",
            type=ParameterType.INTEGER,
            description="Maximum number of entries to return",
            required=False,
            default=500,
            min_value=1,
            max_value=10000,
        ),
        ToolParameter(
            name="exclude",
            type=ParameterType.ARRAY,
            array_item_type=ParameterType.STRING,
            description="Path patterns to exclude (defaults skip vendored dirs)",
            required=False,
            default=list(DEFAULT_EXCLUDE_PATTERNS),
        ),
        ToolParameter(
            name="sort_by",
            type=ParameterType.STRING,
            description="Sort key: name | size | modified | type",
            required=False,
            default="name",
            enum=sorted(_SORT_KEYS),
        ),
    ]


def _file_list_examples() -> list[dict[str, Any]]:
    return [
        {
            "input": {"path": "Z:/测试目录"},
            "output": "Lists files inside Z:/测试目录 with Unicode names intact.",
        },
        {
            "input": {"path": "src", "recursive": True, "max_depth": 2},
            "output": "Two-level deep listing of src/.",
        },
    ]


def _file_list_request(
    parameters: Dict[str, Any],
    context: ToolExecutionContext,
) -> _FileListRequest:
    return _FileListRequest(
        target_path=resolve_path_from_workspace(
            parameters.get("path", "."),
            workspace=context.workspace,
            default=".",
        ),
        recursive=bool(parameters.get("recursive", False)),
        include_hidden=bool(parameters.get("include_hidden", False)),
        max_depth=int(parameters.get("max_depth", 8)),
        max_entries=int(parameters.get("max_entries", 500)),
        exclude_patterns=normalize_exclude_patterns(parameters.get("exclude")),
        sort_by=str(parameters.get("sort_by", "name")).lower(),
    )


def _sort_entries(entries: list[dict[str, Any]], sort_by: str) -> None:
    sort_key_map = {
        "name": lambda item: item["name"].lower(),
        "size": lambda item: item.get("size", 0) or 0,
        "modified": lambda item: item.get("modified", 0) or 0,
        "type": lambda item: (item.get("kind", ""), item["name"].lower()),
    }
    entries.sort(key=sort_key_map[sort_by])


class FileListTool(Tool):
    """List entries inside a directory with structured metadata."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="file_list",
            description=(
                "List the entries inside a directory and return structured "
                "metadata (name, kind, size, modified time). Prefer this over "
                "running `dir` or `ls` through the bash tool — it is "
                "Unicode-safe across Windows/macOS/Linux and avoids console "
                "code-page issues."
            ),
            category="file",
            version="1.0.0",
            author="Magi Team",
            parameters=_file_list_parameters(),
            examples=_file_list_examples(),
            timeout=15,
            retry_on_failure=False,
            dangerous=False,
            effect_replay_policy="read_only",
            tags=["file", "directory", "list", "structured"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        request = _file_list_request(parameters, context)
        if request.sort_by not in _SORT_KEYS:
            return ToolResult(
                success=False,
                error=f"Invalid sort_by '{request.sort_by}'. Allowed: {sorted(_SORT_KEYS)}",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        target_error = self._validate_target(request.target_path)
        if target_error is not None:
            return target_error

        entries: List[Dict[str, Any]] = []
        try:
            truncated = self._collect_entries(request, entries)
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
                error_code=ToolErrorCode.LIST_ERROR.value,
            )

        _sort_entries(entries, request.sort_by)
        return ToolResult(
            success=True,
            data=self._result_data(request, entries, truncated),
        )

    def _validate_target(self, target_path: str) -> ToolResult | None:
        if not os.path.exists(target_path):
            return ToolResult(
                success=False,
                error=f"Path not found: {target_path}",
                error_code=ToolErrorCode.PATH_NOT_FOUND.value,
            )
        if not os.path.isdir(target_path):
            return ToolResult(
                success=False,
                error=f"Path is not a directory: {target_path}",
                error_code=ToolErrorCode.NOT_A_DIRECTORY.value,
            )
        return None

    def _collect_entries(
        self,
        request: _FileListRequest,
        entries: List[Dict[str, Any]],
    ) -> bool:
        return self._walk(
            request.target_path,
            base_path=request.target_path,
            depth=0,
            max_depth=request.max_depth if request.recursive else 1,
            include_hidden=request.include_hidden,
            exclude_patterns=request.exclude_patterns,
            max_entries=request.max_entries,
            entries=entries,
        )

    def _result_data(
        self,
        request: _FileListRequest,
        entries: list[dict[str, Any]],
        truncated: bool,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "path": request.target_path,
            "recursive": request.recursive,
            "count": len(entries),
            "truncated": truncated,
            "entries": entries,
        }
        # Nudge the model toward the batch orchestrator when a listing surfaces
        # many homogeneous files, so it hands off to batch_create instead of
        # looping one-by-one into the per-turn iteration cap.
        batch_hint = suggest_batch([item["name"] for item in entries if item.get("is_file")])
        if batch_hint:
            data["batch_hint"] = batch_hint
        return data

    def _walk(
        self,
        directory: str,
        *,
        base_path: str,
        depth: int,
        max_depth: int,
        include_hidden: bool,
        exclude_patterns: List[str],
        max_entries: int,
        entries: List[Dict[str, Any]],
    ) -> bool:
        if depth >= max_depth:
            return False

        try:
            iterator = os.scandir(directory)
        except (PermissionError, OSError):
            return False

        with iterator as scan:
            for entry in scan:
                if len(entries) >= max_entries:
                    return True

                entry_data = self._entry_data(
                    entry,
                    base_path=base_path,
                    depth=depth,
                    include_hidden=include_hidden,
                    exclude_patterns=exclude_patterns,
                )
                if entry_data is None:
                    continue

                entries.append(entry_data)

                if entry_data["is_dir"] and not entry_data["is_symlink"] and depth + 1 < max_depth:
                    if self._walk(
                        entry.path,
                        base_path=base_path,
                        depth=depth + 1,
                        max_depth=max_depth,
                        include_hidden=include_hidden,
                        exclude_patterns=exclude_patterns,
                        max_entries=max_entries,
                        entries=entries,
                    ):
                        return True

        return False

    def _entry_data(
        self,
        entry: os.DirEntry,
        *,
        base_path: str,
        depth: int,
        include_hidden: bool,
        exclude_patterns: List[str],
    ) -> Dict[str, Any] | None:
        relative_path = self._relative_path(entry, base_path)
        if not include_hidden and has_hidden_path_component(relative_path):
            return None
        if matches_exclude_path(relative_path, exclude_patterns):
            return None

        try:
            is_symlink = entry.is_symlink()
            entry_stat = entry.stat(follow_symlinks=False)
        except (PermissionError, OSError):
            return None

        kind = _entry_kind(entry_stat, is_symlink)
        is_dir = kind == "directory" or (is_symlink and entry.is_dir(follow_symlinks=True))
        return {
            "name": entry.name,
            "path": entry.path,
            "relative_path": relative_path,
            "kind": kind,
            "is_dir": is_dir,
            "is_file": kind == "file",
            "is_symlink": is_symlink,
            "size": entry_stat.st_size if kind == "file" else 0,
            "modified": entry_stat.st_mtime,
            "depth": depth,
        }

    def _relative_path(self, entry: os.DirEntry, base_path: str) -> str:
        try:
            return os.path.relpath(entry.path, base_path)
        except ValueError:
            return entry.path
