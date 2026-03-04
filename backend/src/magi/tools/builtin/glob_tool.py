"""
Glob tool - Find files matching patterns
"""
import os
import fnmatch
from typing import Dict, Any, List
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType, ToolErrorCode


class GlobTool(Tool):
    """
    Glob tool

    Find files and directories matching shell-style patterns
    """

    def _init_schema(self) -> None:
        """Initialize schema"""
        self.schema = ToolSchema(
            name="glob",
            description="Find files matching shell-style patterns (like *.py, **/*.ts)",
            category="file",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="pattern",
                    type=ParameterType.STRING,
                    description="Glob pattern to match files (e.g., *.py, **/*.ts, src/**/*.js)",
                    required=True,
                ),
                ToolParameter(
                    name="path",
                    type=ParameterType.STRING,
                    description="Base directory to search from",
                    required=False,
                    default=".",
                ),
                ToolParameter(
                    name="recursive",
                    type=ParameterType.BOOLEAN,
                    description="Use ** for recursive matching",
                    required=False,
                    default=True,
                ),
                ToolParameter(
                    name="include_hidden",
                    type=ParameterType.BOOLEAN,
                    description="Include hidden files (starting with .)",
                    required=False,
                    default=False,
                ),
                ToolParameter(
                    name="directories_only",
                    type=ParameterType.BOOLEAN,
                    description="Only match directories, not files",
                    required=False,
                    default=False,
                ),
                ToolParameter(
                    name="files_only",
                    type=ParameterType.BOOLEAN,
                    description="Only match files, not directories",
                    required=False,
                    default=True,
                ),
                ToolParameter(
                    name="max_results",
                    type=ParameterType.INTEGER,
                    description="Maximum number of results to return",
                    required=False,
                    default=1000,
                    min_value=1,
                    max_value=10000,
                ),
            ],
            examples=[
                {
                    "input": {"pattern": "*.py"},
                    "output": "Find all Python files in current directory",
                },
                {
                    "input": {"pattern": "**/*.ts", "path": "/src"},
                    "output": "Find all TypeScript files recursively in /src",
                },
                {
                    "input": {"pattern": "test_*", "directories_only": True},
                    "output": "Find all directories starting with test_",
                },
            ],
            timeout=30,
            retry_on_failure=False,
            dangerous=False,
            tags=["file", "find", "pattern", "glob"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute glob search"""
        pattern = parameters["pattern"]
        base_path = parameters.get("path", ".")
        recursive = parameters.get("recursive", True)
        include_hidden = parameters.get("include_hidden", False)
        directories_only = parameters.get("directories_only", False)
        files_only = parameters.get("files_only", True)
        max_results = parameters.get("max_results", 1000)

        try:
            # Validate base path exists
            if not os.path.exists(base_path):
                return ToolResult(
                    success=False,
                    error=f"Path not found: {base_path}",
                    error_code=ToolErrorCode.PATH_NOT_FOUND.value
                )

            if not os.path.isdir(base_path):
                return ToolResult(
                    success=False,
                    error=f"Path is not a directory: {base_path}",
                    error_code=ToolErrorCode.NOT_A_DIRECTORY.value
                )

            matches: List[Dict[str, Any]] = []

            # Check if pattern uses ** for recursive
            use_recursive = recursive or "**" in pattern
            # Normalize pattern (remove ** if present, we handle recursion manually)
            normalized_pattern = pattern.replace("**/", "").replace("/**", "")

            def match_item(item_path: str) -> None:
                """Check if item matches pattern and add to results"""
                if len(matches) >= max_results:
                    return

                try:
                    is_dir = os.path.isdir(item_path)
                    is_file = os.path.isfile(item_path)

                    # Filter by type
                    if directories_only and not is_dir:
                        return
                    if files_only and not is_file:
                        return

                    # Get item name for matching
                    item_name = os.path.basename(item_path)

                    # Check pattern match
                    if fnmatch.fnmatch(item_name, normalized_pattern):
                        stat = os.stat(item_path)
                        matches.append({
                            "path": item_path,
                            "name": item_name,
                            "is_file": is_file,
                            "is_dir": is_dir,
                            "size": stat.st_size if is_file else 0,
                            "modified": stat.st_mtime,
                        })
                except (PermissionError, OSError):
                    pass

            # Walk directory tree
            if use_recursive:
                for root, dirs, files in os.walk(base_path):
                    # Filter hidden directories
                    if not include_hidden:
                        dirs[:] = [d for d in dirs if not d.startswith(".")]

                    # Check directories
                    if not files_only:
                        for d in dirs:
                            if len(matches) >= max_results:
                                break
                            match_item(os.path.join(root, d))

                    # Check files
                    if not directories_only:
                        for f in files:
                            if len(matches) >= max_results:
                                break
                            if not include_hidden and f.startswith("."):
                                continue
                            match_item(os.path.join(root, f))

                    if len(matches) >= max_results:
                        break
            else:
                # Non-recursive, only search immediate directory
                for item in os.listdir(base_path):
                    if len(matches) >= max_results:
                        break
                    if not include_hidden and item.startswith("."):
                        continue
                    match_item(os.path.join(base_path, item))

            # Sort by modification time (most recent first)
            matches.sort(key=lambda x: x["modified"], reverse=True)

            result_data = {
                "pattern": pattern,
                "base_path": base_path,
                "matches": matches,
                "count": len(matches),
                "truncated": len(matches) >= max_results,
            }

            return ToolResult(
                success=True,
                data=result_data,
            )

        except PermissionError:
            return ToolResult(
                success=False,
                error=f"Permission denied accessing: {base_path}",
                error_code=ToolErrorCode.PERMISSION_DENIED.value
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code=ToolErrorCode.EXECUTION_ERROR.value
            )
