"""
文件读取工具
"""
import os
from typing import Dict, Any
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType


class FileReadTool(Tool):
    """
    文件读取工具

    读取文本文件内容
    """

    def _init_schema(self) -> None:
        """初始化Schema"""
        self.schema = ToolSchema(
            name="file_read",
            description="读取文件内容",
            category="file",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="path",
                    type=ParameterType.STRING,
                    description="文件路径",
                    required=True,
                ),
                ToolParameter(
                    name="encoding",
                    type=ParameterType.STRING,
                    description="文件编码",
                    required=False,
                    default="utf-8",
                ),
                ToolParameter(
                    name="offset",
                    type=ParameterType.INTEGER,
                    description="读取起始位置（字节）",
                    required=False,
                    default=0,
                    min_value=0,
                ),
                ToolParameter(
                    name="limit",
                    type=ParameterType.INTEGER,
                    description="读取最大字节数",
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
        """读取文件"""
        file_path = parameters["path"]
        encoding = parameters.get("encoding", "utf-8")
        offset = parameters.get("offset", 0)
        limit = parameters.get("limit")

        try:
            # 检查文件是否存在
            if not os.path.exists(file_path):
                return ToolResult(
                    success=False,
                    error=f"File not found: {file_path}",
                    error_code="FILE_NOT_FOUND"
                )

            # 检查是否是文件
            if not os.path.isfile(file_path):
                return ToolResult(
                    success=False,
                    error=f"Path is not a file: {file_path}",
                    error_code="NOT_A_FILE"
                )

            # 检查文件大小
            file_size = os.path.getsize(file_path)
            if offset >= file_size:
                return ToolResult(
                    success=False,
                    error=f"Offset {offset} is beyond file size {file_size}",
                    error_code="OFFSET_OUT_OF_RANGE"
                )

            # 读取文件
            with open(file_path, "r", encoding=encoding) as f:
                if offset > 0:
                    f.seek(offset)

                if limit:
                    content = f.read(limit)
                else:
                    content = f.read()

            # 准备结果
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

        except PermissionError:
            return ToolResult(
                success=False,
                error=f"Permission denied reading file: {file_path}",
                error_code="PERMISSION_DENIED"
            )
        except UnicodeDecodeError as e:
            return ToolResult(
                success=False,
                error=f"Failed to decode file with encoding {encoding}: {str(e)}",
                error_code="DECODE_ERROR"
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code="READ_ERROR"
            )
