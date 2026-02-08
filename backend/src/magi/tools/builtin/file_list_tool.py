"""
文件列表工具
"""
import os
from typing import Dict, Any, List
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType


class FileListTool(Tool):
    """
    文件列表工具

    列出目录中的文件和子目录
    """

    def _init_schema(self) -> None:
        """初始化Schema"""
        self.schema = ToolSchema(
            name="file_list",
            description="列出目录内容",
            category="file",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="path",
                    type=ParameterType.STRING,
                    description="目录路径",
                    required=True,
                ),
                ToolParameter(
                    name="recursive",
                    type=ParameterType.BOOLEAN,
                    description="是否递归列出子目录",
                    required=False,
                    default=False,
                ),
                ToolParameter(
                    name="include_hidden",
                    type=ParameterType.BOOLEAN,
                    description="是否包含隐藏文件（以.开头）",
                    required=False,
                    default=False,
                ),
                ToolParameter(
                    name="pattern",
                    type=ParameterType.STRING,
                    description="文件名模式过滤（如*.txt）",
                    required=False,
                ),
            ],
            examples=[
                {
                    "input": {"path": "/tmp"},
                    "output": "Lists all files in /tmp",
                },
                {
                    "input": {"path": ".", "pattern": "*.py", "recursive": True},
                    "output": "Lists all Python files recursively",
                },
            ],
            timeout=10,
            retry_on_failure=False,
            dangerous=False,
            tags=["file", "list", "io"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """列出文件"""
        dir_path = parameters["path"]
        recursive = parameters.get("recursive", False)
        include_hidden = parameters.get("include_hidden", False)
        pattern = parameters.get("pattern")

        try:
            # 检查路径是否存在
            if not os.path.exists(dir_path):
                return ToolResult(
                    success=False,
                    error=f"Path not found: {dir_path}",
                    error_code="PATH_NOT_FOUND"
                )

            # 检查是否是目录
            if not os.path.isdir(dir_path):
                return ToolResult(
                    success=False,
                    error=f"Path is not a directory: {dir_path}",
                    error_code="NOT_A_DIRECTORY"
                )

            import fnmatch

            items: List[Dict[str, Any]] = []

            if recursive:
                # 递归列出所有文件
                for root, dirs, files in os.walk(dir_path):
                    # 过滤隐藏目录
                    if not include_hidden:
                        dirs[:] = [d for d in dirs if not d.startswith(".")]

                    for file in files:
                        # 过滤隐藏文件
                        if not include_hidden and file.startswith("."):
                            continue

                        # 模式过滤
                        if pattern and not fnmatch.fnmatch(file, pattern):
                            continue

                        # 获取文件信息
                        full_path = os.path.join(root, file)
                        stat = os.stat(full_path)

                        items.append({
                            "name": file,
                            "path": full_path,
                            "size": stat.st_size,
                            "is_file": True,
                            "is_dir": False,
                            "modified": stat.st_mtime,
                        })
            else:
                # 非递归，只列出直接子项
                for item in os.listdir(dir_path):
                    # 过滤隐藏文件
                    if not include_hidden and item.startswith("."):
                        continue

                    # 模式过滤
                    if pattern and not fnmatch.fnmatch(item, pattern):
                        continue

                    full_path = os.path.join(dir_path, item)
                    stat = os.stat(full_path)

                    items.append({
                        "name": item,
                        "path": full_path,
                        "size": stat.st_size,
                        "is_file": os.path.isfile(full_path),
                        "is_dir": os.path.isdir(full_path),
                        "modified": stat.st_mtime,
                    })

            result_data = {
                "path": dir_path,
                "items": items,
                "count": len(items),
            }

            return ToolResult(
                success=True,
                data=result_data,
            )

        except PermissionError:
            return ToolResult(
                success=False,
                error=f"Permission denied accessing directory: {dir_path}",
                error_code="PERMISSION_DENIED"
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code="LIST_ERROR"
            )
