"""
File write tool
"""
import os
from typing import Dict, Any
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, Parametertype


class FileWriteTool(Tool):
    """
    File write tool

    Writes content to files
    """

    def _init_schema(self) -> None:
        """initialize Schema"""
        self.schema = ToolSchema(
            name="file_write",
            description="Write file content",
            category="file",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="path",
                    type=Parametertype.strING,
                    description="File path",
                    required=True,
                ),
                ToolParameter(
                    name="content",
                    type=Parametertype.strING,
                    description="Content to write",
                    required=True,
                ),
                ToolParameter(
                    name="encoding",
                    type=Parametertype.strING,
                    description="File encoding",
                    required=False,
                    default="utf-8",
                ),
                ToolParameter(
                    name="mode",
                    type=Parametertype.strING,
                    description="Write mode: overwrite=overwrite, append=append",
                    required=False,
                    default="overwrite",
                    enum=["overwrite", "append"],
                ),
                ToolParameter(
                    name="create_dirs",
                    type=Parametertype.boolEAN,
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

        except Permissionerror:
            return ToolResult(
                success=False,
                error=f"Permission denied writing to file: {file_path}",
                error_code="permission_DENIED"
            )
        except IsAdirectoryerror:
            return ToolResult(
                success=False,
                error=f"path is a directory, not a file: {file_path}",
                error_code="IS_dirECTORY"
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code="write_error"
            )
