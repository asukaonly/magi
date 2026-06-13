"""
Glob tool - Find files matching patterns
"""
import os
from pathlib import Path
from typing import Dict, Any, List
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType, ToolErrorCode
from ..utils.batch_autodetect import suggest_batch
from ..utils.path_utils import (
    DEFAULT_EXCLUDE_PATTERNS,
    has_hidden_path_component,
    matches_exclude_path,
    normalize_exclude_patterns,
    resolve_path_from_workspace,
)


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
                    default=False,
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
                    name="exclude",
                    type=ParameterType.ARRAY,
                    array_item_type=ParameterType.STRING,
                    description="Path patterns to exclude from traversal",
                    required=False,
                    default=list(DEFAULT_EXCLUDE_PATTERNS),
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
                ToolParameter(
                    name="outside_workspace_allowed",
                    type=ParameterType.BOOLEAN,
                    description=(
                        "Set to true ONLY when the user has explicitly asked to scan a "
                        "path outside the active workspace (e.g. another repository, "
                        "an absolute system path, or a sibling directory). Defaults to "
                        "false; the worker guardrail will reject out-of-workspace scans "
                        "without this flag."
                    ),
                    required=False,
                    default=False,
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
            metadata={
                "task_intents": ["explore_codebase", "trace_implementation"],
                "domains": ["codebase"],
                "operations": ["discover"],
                "query_shapes": ["path_or_module", "glob_pattern"],
                "followed_by": ["grep", "file_read"],
                "avoid_task_intents": ["research_external", "clarify_requirement", "recall_context"],
                "cost": "cheap",
                "tool_hint": "Use first to locate candidate files or folders from path or module clues before narrowing with grep or file_read.",
            },
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute glob search"""
        pattern = parameters["pattern"]
        base_path = resolve_path_from_workspace(
            parameters.get("path", "."),
            workspace=context.workspace,
            default=".",
        )
        recursive = parameters.get("recursive", False)
        include_hidden = parameters.get("include_hidden", False)
        directories_only = parameters.get("directories_only", False)
        files_only = parameters.get("files_only", True)
        exclude_patterns = normalize_exclude_patterns(parameters.get("exclude"))
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
            seen_paths: set[str] = set()

            # Preserve recursive behavior for simple file-name patterns.
            # Example: pattern="*.py", recursive=True should search nested directories.
            use_recursive = recursive or "**" in pattern
            pattern_has_path = "/" in pattern or os.sep in pattern
            if use_recursive and "**" not in pattern and not pattern_has_path:
                effective_pattern = f"**/{pattern}"
            else:
                effective_pattern = pattern

            search_root = Path(base_path)

            for item in search_root.glob(effective_pattern):
                normalized_path = os.path.normpath(str(item))
                if normalized_path in seen_paths:
                    continue
                seen_paths.add(normalized_path)

                try:
                    relative_path = os.path.relpath(normalized_path, base_path)
                except ValueError:
                    relative_path = normalized_path

                if not include_hidden and has_hidden_path_component(relative_path):
                    continue
                if matches_exclude_path(relative_path, exclude_patterns):
                    continue

                try:
                    is_dir = os.path.isdir(normalized_path)
                    is_file = os.path.isfile(normalized_path)
                    if directories_only and not is_dir:
                        continue
                    if files_only and not is_file:
                        continue

                    stat = os.stat(normalized_path)
                    matches.append({
                        "path": normalized_path,
                        "name": os.path.basename(normalized_path),
                        "is_file": is_file,
                        "is_dir": is_dir,
                        "size": stat.st_size if is_file else 0,
                        "modified": stat.st_mtime,
                    })
                    if len(matches) >= max_results:
                        break
                except (PermissionError, OSError):
                    continue

            # Sort by modification time (most recent first)
            matches.sort(key=lambda x: x["modified"], reverse=True)

            result_data = {
                "pattern": pattern,
                "base_path": base_path,
                "exclude": exclude_patterns,
                "matches": matches,
                "count": len(matches),
                "truncated": len(matches) >= max_results,
            }
            # Nudge the model toward the batch orchestrator when the pattern
            # surfaces many homogeneous files, so it hands off to batch_create
            # instead of looping one-by-one into the per-turn iteration cap.
            batch_hint = suggest_batch(
                [item["path"] for item in matches if item.get("is_file")]
            )
            if batch_hint:
                result_data["batch_hint"] = batch_hint

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
