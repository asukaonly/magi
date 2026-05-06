"""
File write tool
"""
import os
from typing import Dict, Any
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType, ToolErrorCode
from ._edit_journal import record_edit_after, snapshot_before_edit
from ._read_constraint import require_prior_read


class FileWriteTool(Tool):
    """
    File write tool

    Writes content to files
    """

    def _init_schema(self) -> None:
        """initialize Schema"""
        self.schema = ToolSchema(
            name="file_write",
            description="Write file content. When overwriting an existing file, that file must have been read with file_read in this session first. Creating a new file or appending does not require a prior read.",
            category="file",
            version="1.0.0",
            author="Magi Team",
            parameters=[
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
            ],
            examples=[
                {
                    "input": {
                        "path": "/tmp/test.txt",
                        "content": "Hello, World!",
                        "mode": "overwrite"
                    },
                    "output": "Creates file with content",
                },
                {
                    "input": {
                        "path": "log.txt",
                        "content": "New log entry\n",
                        "mode": "append"
                    },
                    "output": "Appends to existing file",
                },
            ],
            timeout=10,
            retry_on_failure=False,
            dangerous=True,  # Writing files is a dangerous operation
            tags=["file", "write", "io"],
            metadata={
                "task_intents": ["apply_change", "create_artifact"],
                "domains": ["codebase", "docs"],
                "operations": ["edit", "create"],
                "query_shapes": ["new_file", "full_rewrite"],
                "followed_by": [],
                "avoid_task_intents": ["explore_codebase", "trace_implementation", "research_external", "clarify_requirement", "recall_context"],
                "requires_known_target": True,
                "cost": "medium",
                "tool_hint": "Use to create a new file or rewrite full contents once the destination path and content are already settled; prefer file_edit for precise edits.",
            },
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Write to file"""
        file_path = parameters["path"]
        content = parameters["content"]
        encoding = parameters.get("encoding", "utf-8")
        mode = parameters.get("mode", "overwrite")
        create_dirs = parameters.get("create_dirs", False)

        if mode == "overwrite" and os.path.exists(file_path):
            block_msg = require_prior_read(context, file_path)
            if block_msg is not None:
                return ToolResult(
                    success=False,
                    error=block_msg,
                    error_code=ToolErrorCode.INVALID_PARAMETERS.value,
                )

        snapshot_ctx = None
        if mode == "overwrite" and os.path.exists(file_path):
            snapshot_ctx = snapshot_before_edit(context, file_path)

        try:
            # Check and create directory
            directory = os.path.dirname(file_path)
            if directory and create_dirs and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)

            # Write mode
            file_mode = "w" if mode == "overwrite" else "a"

            # Write file
            with open(file_path, file_mode, encoding=encoding) as f:
                bytes_written = f.write(content)

            if snapshot_ctx is not None:
                record_edit_after(context, file_path, snapshot_ctx, op="write")

            # Get file info
            file_size = os.path.getsize(file_path)

            result_data = {
                "path": file_path,
                "bytes_written": bytes_written,
                "file_size": file_size,
                "mode": mode,
                "encoding": encoding,
            }

            return ToolResult(
                success=True,
                data=result_data,
            )

        except PermissionError:
            return ToolResult(
                success=False,
                error=f"Permission denied writing to file: {file_path}",
                error_code=ToolErrorCode.PERMISSION_DENIED.value
            )
        except IsADirectoryError:
            return ToolResult(
                success=False,
                error=f"path is a directory, not a file: {file_path}",
                error_code=ToolErrorCode.IS_DIRECTORY.value
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code=ToolErrorCode.WRITE_ERROR.value
            )
