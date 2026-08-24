"""
File write tool
"""

import os
from dataclasses import dataclass
from typing import Dict, Any

from ..schema import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)
from ._edit_journal import record_edit_after, snapshot_before_edit
from ._read_constraint import require_prior_read


@dataclass(frozen=True)
class _FileWriteRequest:
    path: str
    content: str
    encoding: str
    mode: str
    create_dirs: bool


class FileWriteTool(Tool):
    """
    File write tool

    Writes content to files
    """

    def _init_schema(self) -> None:
        """initialize Schema"""
        self.schema = _build_file_write_schema()

    async def execute(
        self, parameters: Dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """Write to file"""
        request = _parse_file_write_request(parameters)
        blocked_result = _require_prior_read_for_overwrite(context, request)
        if blocked_result is not None:
            return blocked_result

        snapshot_ctx = _snapshot_for_overwrite(context, request)

        try:
            bytes_written = _write_file(request)
            if snapshot_ctx is not None:
                record_edit_after(context, request.path, snapshot_ctx, op="write")
            return _success_result(request, bytes_written)

        except PermissionError:
            return _permission_denied_result(request.path)
        except IsADirectoryError:
            return _is_directory_result(request.path)
        except Exception as e:
            return _write_error_result(e)


def _build_file_write_schema() -> ToolSchema:
    return ToolSchema(
        name="file_write",
        description=(
            "Write file content. When overwriting an existing file, that file must "
            "have been read with file_read in this session first. Creating a new "
            "file or appending does not require a prior read."
        ),
        category="file",
        version="1.0.0",
        author="Magi Team",
        parameters=_file_write_parameters(),
        examples=_file_write_examples(),
        timeout=10,
        retry_on_failure=False,
        dangerous=True,
        effect_class="local_write",
        effect_replay_policy="reconcilable",
        tags=["file", "write", "io"],
        metadata=_file_write_metadata(),
    )


def _file_write_parameters() -> list[ToolParameter]:
    return [
        ToolParameter(
            name="path",
            type=ParameterType.STRING,
            description="File path",
            required=True,
        ),
        ToolParameter(
            name="content",
            type=ParameterType.STRING,
            description="Content to write",
            required=True,
        ),
        ToolParameter(
            name="encoding",
            type=ParameterType.STRING,
            description="File encoding",
            required=False,
            default="utf-8",
        ),
        ToolParameter(
            name="mode",
            type=ParameterType.STRING,
            description="Write mode: overwrite=overwrite, append=append",
            required=False,
            default="overwrite",
            enum=["overwrite", "append"],
        ),
        ToolParameter(
            name="create_dirs",
            type=ParameterType.BOOLEAN,
            description="Whether to automatically create directories",
            required=False,
            default=False,
        ),
    ]


def _file_write_examples() -> list[dict[str, Any]]:
    return [
        {
            "input": {
                "path": "/tmp/test.txt",
                "content": "Hello, World!",
                "mode": "overwrite",
            },
            "output": "Creates file with content",
        },
        {
            "input": {
                "path": "log.txt",
                "content": "New log entry\n",
                "mode": "append",
            },
            "output": "Appends to existing file",
        },
    ]


def _file_write_metadata() -> dict[str, Any]:
    return {
        "task_intents": ["apply_change", "create_artifact"],
        "domains": ["codebase", "docs"],
        "operations": ["edit", "create"],
        "query_shapes": ["new_file", "full_rewrite"],
        "followed_by": [],
        "avoid_task_intents": [
            "explore_codebase",
            "trace_implementation",
            "research_external",
            "clarify_requirement",
            "recall_context",
        ],
        "requires_known_target": True,
        "cost": "medium",
        "tool_hint": (
            "Use to create a new file or rewrite full contents once the "
            "destination path and content are already settled; prefer file_edit "
            "for precise edits."
        ),
    }


def _parse_file_write_request(parameters: Dict[str, Any]) -> _FileWriteRequest:
    return _FileWriteRequest(
        path=parameters["path"],
        content=parameters["content"],
        encoding=parameters.get("encoding", "utf-8"),
        mode=parameters.get("mode", "overwrite"),
        create_dirs=parameters.get("create_dirs", False),
    )


def _require_prior_read_for_overwrite(
    context: ToolExecutionContext,
    request: _FileWriteRequest,
) -> ToolResult | None:
    if request.mode != "overwrite" or not os.path.exists(request.path):
        return None
    block_msg = require_prior_read(context, request.path)
    if block_msg is None:
        return None
    return ToolResult(
        success=False,
        error=block_msg,
        error_code=ToolErrorCode.INVALID_PARAMETERS.value,
    )


def _snapshot_for_overwrite(
    context: ToolExecutionContext,
    request: _FileWriteRequest,
) -> Any:
    if request.mode == "overwrite" and os.path.exists(request.path):
        return snapshot_before_edit(context, request.path)
    return None


def _write_file(request: _FileWriteRequest) -> int:
    directory = os.path.dirname(request.path)
    if directory and request.create_dirs and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

    file_mode = "w" if request.mode == "overwrite" else "a"
    with open(request.path, file_mode, encoding=request.encoding) as f:
        return f.write(request.content)


def _success_result(request: _FileWriteRequest, bytes_written: int) -> ToolResult:
    return ToolResult(
        success=True,
        data={
            "path": request.path,
            "bytes_written": bytes_written,
            "file_size": os.path.getsize(request.path),
            "mode": request.mode,
            "encoding": request.encoding,
        },
    )


def _permission_denied_result(file_path: str) -> ToolResult:
    return ToolResult(
        success=False,
        error=f"Permission denied writing to file: {file_path}",
        error_code=ToolErrorCode.PERMISSION_DENIED.value,
    )


def _is_directory_result(file_path: str) -> ToolResult:
    return ToolResult(
        success=False,
        error=f"path is a directory, not a file: {file_path}",
        error_code=ToolErrorCode.IS_DIRECTORY.value,
    )


def _write_error_result(error: Exception) -> ToolResult:
    return ToolResult(
        success=False,
        error=str(error),
        error_code=ToolErrorCode.WRITE_ERROR.value,
    )
