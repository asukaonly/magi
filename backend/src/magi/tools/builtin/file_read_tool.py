"""
File read tool
"""

import os
from dataclasses import dataclass
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
from ._read_constraint import record_read_in_session


@dataclass(frozen=True)
class _ReadRequest:
    file_path: str
    encoding: str
    offset: int
    limit: int | None


def _file_read_parameters() -> list[ToolParameter]:
    return [
        ToolParameter(
            name="path",
            type=ParameterType.STRING,
            description="File path",
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
            name="offset",
            type=ParameterType.INTEGER,
            description="Read start position (bytes)",
            required=False,
            default=0,
            min_value=0,
        ),
        ToolParameter(
            name="limit",
            type=ParameterType.INTEGER,
            description="Maximum bytes to read",
            required=False,
            default=None,
            min_value=1,
        ),
    ]


def _file_read_examples() -> list[dict[str, Any]]:
    return [
        {
            "input": {"path": "/tmp/test.txt"},
            "output": "Reads entire file",
        },
        {
            "input": {"path": "config.json", "limit": 1024},
            "output": "Reads first 1KB of file",
        },
    ]


def _file_read_metadata() -> dict[str, Any]:
    return {
        "task_intents": [
            "trace_implementation",
            "verify_source_claim",
            "inspect_config",
        ],
        "domains": ["codebase", "config"],
        "operations": ["verify", "inspect"],
        "query_shapes": ["exact_path", "focused_slice"],
        "followed_by": [],
        "avoid_task_intents": [
            "research_external",
            "clarify_requirement",
            "recall_context",
        ],
        "requires_known_target": True,
        "cost": "medium",
        "tool_hint": (
            "Use after glob or grep has narrowed the target; best for "
            "confirming the controlling code path or verifying a concrete "
            "claim from source."
        ),
    }


def _read_request(
    parameters: Dict[str, Any],
    context: ToolExecutionContext,
) -> _ReadRequest:
    return _ReadRequest(
        file_path=resolve_path_from_workspace(
            parameters.get("path"),
            workspace=context.workspace,
            default=".",
        ),
        encoding=parameters.get("encoding", "utf-8"),
        offset=parameters.get("offset", 0),
        limit=parameters.get("limit"),
    )


def _error_result(error: str, error_code: ToolErrorCode) -> ToolResult:
    return ToolResult(success=False, error=error, error_code=error_code.value)


class FileReadTool(Tool):
    """
    File read tool

    Reads text file content
    """

    def _init_schema(self) -> None:
        """initialize Schema"""
        self.schema = ToolSchema(
            name="file_read",
            description="Read file content",
            category="file",
            version="1.0.0",
            author="Magi Team",
            parameters=_file_read_parameters(),
            examples=_file_read_examples(),
            timeout=10,
            retry_on_failure=False,
            dangerous=False,
            effect_replay_policy="read_only",
            tags=["file", "read", "io"],
            metadata=_file_read_metadata(),
        )

    async def execute(
        self, parameters: Dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """Read file"""
        request = _read_request(parameters, context)

        try:
            file_size = self._validate_target(request)
            if isinstance(file_size, ToolResult):
                return file_size

            content = self._read_content(request)
            record_read_in_session(context, request.file_path)
            return ToolResult(
                success=True,
                data=self._result_data(request, content, file_size),
            )

        except PermissionError:
            return ToolResult(
                success=False,
                error=f"Permission denied reading file: {request.file_path}",
                error_code=ToolErrorCode.PERMISSION_DENIED.value,
            )
        except UnicodeDecodeError as e:
            return ToolResult(
                success=False,
                error=f"Failed to decode file with encoding {request.encoding}: {str(e)}",
                error_code=ToolErrorCode.DECODE_ERROR.value,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code=ToolErrorCode.READ_ERROR.value,
            )

    def _validate_target(self, request: _ReadRequest) -> int | ToolResult:
        if not os.path.exists(request.file_path):
            return _error_result(
                f"File not found: {request.file_path}",
                ToolErrorCode.FILE_NOT_FOUND,
            )

        if not os.path.isfile(request.file_path):
            return _error_result(
                f"path is not a file: {request.file_path}",
                ToolErrorCode.NOT_A_FILE,
            )

        file_size = os.path.getsize(request.file_path)
        if request.offset >= file_size:
            return _error_result(
                f"Offset {request.offset} is beyond file size {file_size}",
                ToolErrorCode.OFFSET_OUT_OF_RANGE,
            )
        return file_size

    def _read_content(self, request: _ReadRequest) -> str:
        with open(request.file_path, "r", encoding=request.encoding) as f:
            if request.offset > 0:
                f.seek(request.offset)
            if request.limit:
                return f.read(request.limit)
            return f.read()

    def _result_data(
        self,
        request: _ReadRequest,
        content: str,
        file_size: int,
    ) -> dict[str, Any]:
        return {
            "path": request.file_path,
            "content": content,
            "size": len(content),
            "encoding": request.encoding,
            "total_size": file_size,
            "is_complete": (request.limit is None) or (len(content) < request.limit),
        }
