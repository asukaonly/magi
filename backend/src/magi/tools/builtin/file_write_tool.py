"""
文件写入工具
"""
import os
from typing import Dict, Any
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType


class FileWriteTool(Tool):
    """
    文件写入工具

    将内容写入文件
    """

    def _init_schema(self) -> None:
        """初始化Schema"""
        self.schema = ToolSchema(
            name="file_write",
            description="写入文件内容",
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
                    name="content",
                    type=ParameterType.STRING,
                    description="要写入的内容",
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
                    name="mode",
                    type=ParameterType.STRING,
                    description="写入模式：overwrite=覆盖, append=追加",
                    required=False,
                    default="overwrite",
                    enum=["overwrite", "append"],
                ),
                ToolParameter(
                    name="create_dirs",
                    type=ParameterType.BOOLEAN,
                    description="是否自动创建目录",
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
                        "content": "New log entry\\n",
                        "mode": "append"
                    },
                    "output": "Appends to existing file",
                },
            ],
            timeout=10,
            retry_on_failure=False,
            dangerous=True,  # 写文件是危险操作
            tags=["file", "write", "io"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """写入文件"""
        file_path = parameters["path"]
        content = parameters["content"]
        encoding = parameters.get("encoding", "utf-8")
        mode = parameters.get("mode", "overwrite")
        create_dirs = parameters.get("create_dirs", False)

        try:
            # 检查并创建目录
            directory = os.path.dirname(file_path)
            if directory and create_dirs and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)

            # 写入模式
            file_mode = "w" if mode == "overwrite" else "a"

            # 写入文件
            with open(file_path, file_mode, encoding=encoding) as f:
                bytes_written = f.write(content)

            # 获取文件信息
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
                error_code="PERMISSION_DENIED"
            )
        except IsADirectoryError:
            return ToolResult(
                success=False,
                error=f"Path is a directory, not a file: {file_path}",
                error_code="IS_DIRECTORY"
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code="WRITE_ERROR"
            )
