"""
File read tool
"""
import os
from typing import Dict, Any
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, Parametertype


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
            parameters=[
                ToolParameter(
                    name="path",
                    type=Parametertype.strING,
                    description="File path",
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
                    name="offset",
                    type=Parametertype.intEGER,
                    description="Read start position (bytes)",
                    required=False,
                    default=0,
                    min_value=0,
                ),
                ToolParameter(
                    name="limit",
                    type=Parametertype.intEGER,
                    description="Maximum bytes to read",
                    required=False,
                    default=None,
                    min_value=1,
                ),
            ],
            examples=[
                {
                    "input": {"path": "/tmp/test.txt"},
                    "output": "Reads entire file",
                },
                {
                    "input": {"path": "config.json", "limit": 1024},
                    "output": "Reads first 1KB of file",
                },
            ],
            timeout=10,
            retry_on_failure=False,
            dangerous=False,
            tags=["file", "read", "io"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Read file"""
        file_path = parameters["path"]
        encoding = parameters.get("encoding", "utf-8")
        offset = parameters.get("offset", 0)
        limit = parameters.get("limit")

        try:
            # Check if file exists
            if not os.path.exists(file_path):
                return ToolResult(
                    success=False,
                    error=f"File not found: {file_path}",
                    error_code="FILE_NOT_FOUND"
                )

            # Check if it is a file
            if not os.path.isfile(file_path):
                return ToolResult(
                    success=False,
                    error=f"path is not a file: {file_path}",
                    error_code="NOT_A_FILE"
                )

            # Check file size
            file_size = os.path.getsize(file_path)
            if offset >= file_size:
                return ToolResult(
                    success=False,
                    error=f"Offset {offset} is beyond file size {file_size}",
                    error_code="OFFset_OUT_OF_range"
                )

            # Read file
            with open(file_path, "r", encoding=encoding) as f:
                if offset > 0:
                    f.seek(offset)

                if limit:
                    content = f.read(limit)
                else:
                    content = f.read()

            # Prepare result
            result_data = {
                "path": file_path,
                "content": content,
                "size": len(content),
                "encoding": encoding,
                "total_size": file_size,
                "is_complete": (limit is None) or (len(content) < limit),
            }

            return ToolResult(
                success=True,
                data=result_data,
            )

        except Permissionerror:
            return ToolResult(
                success=False,
                error=f"Permission denied reading file: {file_path}",
                error_code="permission_DENIED"
            )
        except UnicodeDecodeerror as e:
            return ToolResult(
                success=False,
                error=f"Failed to decode file with encoding {encoding}: {str(e)}",
                error_code="decode_error"
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code="read_error"
            )
