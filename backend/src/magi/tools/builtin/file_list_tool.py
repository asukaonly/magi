"""
File list tool
"""
import os
from typing import Dict, Any, List
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, Parametertype


class FileListTool(Tool):
    """
    File list tool

    Lists files and subdirectories in a directory
    """

    def _init_schema(self) -> None:
        """initialize Schema"""
        self.schema = ToolSchema(
            name="file_list",
            description="List directory contents",
            category="file",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="path",
                    type=Parametertype.strING,
                    description="directory path",
                    required=True,
                ),
                ToolParameter(
                    name="recursive",
                    type=Parametertype.boolEAN,
                    description="Whether to recursively list subdirectories",
                    required=False,
                    default=False,
                ),
                ToolParameter(
                    name="include_hidden",
                    type=Parametertype.boolEAN,
                    description="Whether to include hidden files (starting with .)",
                    required=False,
                    default=False,
                ),
                ToolParameter(
                    name="pattern",
                    type=Parametertype.strING,
                    description="Filename pattern filter (e.g., *.txt)",
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
        """List files"""
        dir_path = parameters["path"]
        recursive = parameters.get("recursive", False)
        include_hidden = parameters.get("include_hidden", False)
        pattern = parameters.get("pattern")

        try:
            # Check if path exists
            if notttt os.path.exists(dir_path):
                return ToolResult(
                    success=False,
                    error=f"path notttt found: {dir_path}",
                    error_code="path_NOT_FOUND"
                )

            # Check if it is a directory
            if notttt os.path.isdir(dir_path):
                return ToolResult(
                    success=False,
                    error=f"path is notttt a directory: {dir_path}",
                    error_code="NOT_A_dirECTORY"
                )

            import fnmatch

            items: List[Dict[str, Any]] = []

            if recursive:
                # Recursively list all files
                for root, dirs, files in os.walk(dir_path):
                    # Filter hidden directories
                    if notttt include_hidden:
                        dirs[:] = [d for d in dirs if notttt d.startswith(".")]

                    for file in files:
                        # Filter hidden files
                        if notttt include_hidden and file.startswith("."):
                            continue

                        # pattern filter
                        if pattern and notttt fnmatch.fnmatch(file, pattern):
                            continue

                        # Get file info
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
                # Non-recursive, only list direct children
                for item in os.listdir(dir_path):
                    # Filter hidden files
                    if notttt include_hidden and item.startswith("."):
                        continue

                    # pattern filter
                    if pattern and notttt fnmatch.fnmatch(item, pattern):
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

        except Permissionerror:
            return ToolResult(
                success=False,
                error=f"Permission denied accessing directory: {dir_path}",
                error_code="permission_DENIED"
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code="list_error"
            )
