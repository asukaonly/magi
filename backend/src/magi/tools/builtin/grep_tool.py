"""
Grep tool - Search file contents using regex patterns
"""
import os
import re
import fnmatch
from typing import Dict, Any, List
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType, ToolErrorCode
from ..utils.path_utils import (
    DEFAULT_EXCLUDE_PATTERNS,
    matches_exclude_path,
    normalize_exclude_patterns,
    resolve_path_from_workspace,
)


class GrepTool(Tool):
    """
    Grep tool

    Search for regex patterns in file contents
    """

    def _init_schema(self) -> None:
        """Initialize schema"""
        self.schema = ToolSchema(
            name="grep",
            description="Search for patterns in file contents using regex",
            category="file",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="pattern",
                    type=ParameterType.STRING,
                    description="Regex pattern to search for",
                    required=True,
                ),
                ToolParameter(
                    name="path",
                    type=ParameterType.STRING,
                    description="Directory or file path to search in",
                    required=False,
                    default=".",
                ),
                ToolParameter(
                    name="glob",
                    type=ParameterType.STRING,
                    description="File pattern to match (e.g., *.py, *.ts)",
                    required=False,
                    default="*",
                ),
                ToolParameter(
                    name="ignore_case",
                    type=ParameterType.BOOLEAN,
                    description="Case insensitive search",
                    required=False,
                    default=False,
                ),
                ToolParameter(
                    name="recursive",
                    type=ParameterType.BOOLEAN,
                    description="Search recursively in subdirectories",
                    required=False,
                    default=True,
                ),
                ToolParameter(
                    name="max_results",
                    type=ParameterType.INTEGER,
                    description="Maximum number of matches to return",
                    required=False,
                    default=100,
                    min_value=1,
                    max_value=1000,
                ),
                ToolParameter(
                    name="context_lines",
                    type=ParameterType.INTEGER,
                    description="Number of context lines before and after match",
                    required=False,
                    default=0,
                    min_value=0,
                    max_value=10,
                ),
                ToolParameter(
                    name="exclude",
                    type=ParameterType.ARRAY,
                    description="Path patterns to exclude from traversal",
                    required=False,
                    default=list(DEFAULT_EXCLUDE_PATTERNS),
                ),
            ],
            examples=[
                {
                    "input": {"pattern": "TODO", "path": "/src"},
                    "output": "Find all TODO comments in /src",
                },
                {
                    "input": {"pattern": "def \\w+", "glob": "*.py", "ignore_case": False},
                    "output": "Find all function definitions in Python files",
                },
            ],
            timeout=30,
            retry_on_failure=False,
            dangerous=False,
            tags=["file", "search", "regex", "grep"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute grep search"""
        pattern = parameters["pattern"]
        search_path = resolve_path_from_workspace(
            parameters.get("path", "."),
            workspace=context.workspace,
            default=".",
        )
        file_pattern = parameters.get("glob", "*")
        ignore_case = parameters.get("ignore_case", False)
        recursive = parameters.get("recursive", True)
        max_results = parameters.get("max_results", 100)
        context_lines = parameters.get("context_lines", 0)
        exclude_patterns = normalize_exclude_patterns(parameters.get("exclude"))

        try:
            # Validate path exists
            if not os.path.exists(search_path):
                return ToolResult(
                    success=False,
                    error=f"Path not found: {search_path}",
                    error_code=ToolErrorCode.PATH_NOT_FOUND.value
                )

            # Compile regex pattern
            flags = re.IGNORECASE if ignore_case else 0
            try:
                regex = re.compile(pattern, flags)
            except re.error as e:
                return ToolResult(
                    success=False,
                    error=f"Invalid regex pattern: {str(e)}",
                    error_code=ToolErrorCode.INVALID_PARAMETERS.value
                )

            matches: List[Dict[str, Any]] = []
            files_searched = 0
            total_matches = 0

            def search_file(file_path: str) -> List[Dict[str, Any]]:
                """Search a single file for matches"""
                file_matches = []
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()

                    for i, line in enumerate(lines):
                        if regex.search(line):
                            # Build context
                            context_before = []
                            context_after = []

                            if context_lines > 0:
                                start = max(0, i - context_lines)
                                end = min(len(lines), i + context_lines + 1)
                                context_before = [
                                    {"line_number": j + 1, "content": lines[j].rstrip("\n\r")}
                                    for j in range(start, i)
                                ]
                                context_after = [
                                    {"line_number": j + 1, "content": lines[j].rstrip("\n\r")}
                                    for j in range(i + 1, end)
                                ]

                            file_matches.append({
                                "file": file_path,
                                "line_number": i + 1,
                                "content": line.rstrip("\n\r"),
                                "context_before": context_before,
                                "context_after": context_after,
                            })
                except (PermissionError, UnicodeDecodeError):
                    pass  # Skip files we can't read
                return file_matches

            pattern_has_path = "/" in file_pattern or os.sep in file_pattern
            normalized_file_pattern = file_pattern.replace(os.sep, "/")

            def matches_file_glob(relative_path: str, filename: str) -> bool:
                """Match file name/path against glob with basic ** compatibility."""
                if not pattern_has_path:
                    return fnmatch.fnmatch(filename, normalized_file_pattern)
                if fnmatch.fnmatch(relative_path, normalized_file_pattern):
                    return True
                if "**/" in normalized_file_pattern:
                    collapsed_pattern = normalized_file_pattern.replace("**/", "")
                    if fnmatch.fnmatch(relative_path, collapsed_pattern):
                        return True
                return False

            # Walk directory or search single file
            if os.path.isfile(search_path):
                relative_path = os.path.basename(search_path)
                if matches_exclude_path(relative_path, exclude_patterns):
                    return ToolResult(
                        success=True,
                        data={
                            "pattern": pattern,
                            "path": search_path,
                            "glob": file_pattern,
                            "exclude": exclude_patterns,
                            "matches": [],
                            "match_count": 0,
                            "files_searched": 0,
                            "truncated": False,
                        },
                    )
                files_searched = 1
                matches.extend(search_file(search_path))
            else:
                if recursive:
                    for root, dirs, files in os.walk(search_path):
                        # Skip hidden directories
                        dirs[:] = [d for d in dirs if not d.startswith(".")]
                        rel_dirs = [(d, os.path.relpath(os.path.join(root, d), search_path)) for d in dirs]
                        dirs[:] = [name for name, rel in rel_dirs if not matches_exclude_path(rel, exclude_patterns)]

                        for filename in files:
                            file_path = os.path.join(root, filename)
                            relative_path = os.path.relpath(file_path, search_path).replace(os.sep, "/")
                            if matches_exclude_path(relative_path, exclude_patterns):
                                continue
                            if not matches_file_glob(relative_path, filename):
                                continue
                            if len(matches) >= max_results:
                                break
                            file_matches = search_file(file_path)
                            files_searched += 1

                            for m in file_matches:
                                if len(matches) >= max_results:
                                    break
                                matches.append(m)
                                total_matches += 1

                        if len(matches) >= max_results:
                            break
                else:
                    for item in os.listdir(search_path):
                        file_path = os.path.join(search_path, item)
                        relative_path = os.path.relpath(file_path, search_path).replace(os.sep, "/")
                        if matches_exclude_path(relative_path, exclude_patterns):
                            continue
                        if not matches_file_glob(relative_path, item):
                            continue
                        if os.path.isfile(file_path):
                            file_matches = search_file(file_path)
                            files_searched += 1
                            matches.extend(file_matches)

            result_data = {
                "pattern": pattern,
                "path": search_path,
                "glob": file_pattern,
                "exclude": exclude_patterns,
                "matches": matches,
                "match_count": len(matches),
                "files_searched": files_searched,
                "truncated": len(matches) >= max_results,
            }

            return ToolResult(
                success=True,
                data=result_data,
            )

        except PermissionError:
            return ToolResult(
                success=False,
                error=f"Permission denied accessing: {search_path}",
                error_code=ToolErrorCode.PERMISSION_DENIED.value
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code=ToolErrorCode.EXECUTION_ERROR.value
            )
