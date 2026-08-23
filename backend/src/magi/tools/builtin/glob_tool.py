"""
Glob tool - Find files matching patterns
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List
from ..schema import (
    Tool,
    ToolSchema,
    ToolExecutionContext,
    ToolResult,
    ToolParameter,
    ParameterType,
    ToolErrorCode,
)
from ..utils.batch_autodetect import suggest_batch
from ..utils.path_utils import (
    DEFAULT_EXCLUDE_PATTERNS,
    has_hidden_path_component,
    matches_exclude_path,
    normalize_exclude_patterns,
    resolve_path_from_workspace,
)


@dataclass(frozen=True)
class _GlobRequest:
    pattern: str
    base_path: str
    recursive: bool
    include_hidden: bool
    directories_only: bool
    files_only: bool
    exclude_patterns: list[str]
    max_results: int


def _glob_core_parameters() -> list[ToolParameter]:
    return [
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
    ]


def _glob_filter_parameters() -> list[ToolParameter]:
    return [
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
    ]


def _glob_parameters() -> list[ToolParameter]:
    return [*_glob_core_parameters(), *_glob_filter_parameters()]


def _glob_examples() -> list[dict[str, Any]]:
    return [
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
    ]


def _glob_metadata() -> dict[str, Any]:
    return {
        "task_intents": ["explore_codebase", "trace_implementation"],
        "domains": ["codebase"],
        "operations": ["discover"],
        "query_shapes": ["path_or_module", "glob_pattern"],
        "followed_by": ["grep", "file_read"],
        "avoid_task_intents": [
            "research_external",
            "clarify_requirement",
            "recall_context",
        ],
        "cost": "cheap",
        "tool_hint": "Use first to locate candidate files or folders from path or module clues before narrowing with grep or file_read.",
    }


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
            parameters=_glob_parameters(),
            examples=_glob_examples(),
            timeout=30,
            retry_on_failure=False,
            dangerous=False,
            effect_replay_policy="read_only",
            tags=["file", "find", "pattern", "glob"],
            metadata=_glob_metadata(),
        )

    async def execute(
        self, parameters: Dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """Execute glob search"""
        request = self._build_glob_request(parameters, context)

        try:
            invalid_path = self._validate_base_path(request.base_path)
            if invalid_path is not None:
                return invalid_path

            matches = self._collect_matches(request)
            result_data = self._build_result_data(request, matches)

            return ToolResult(
                success=True,
                data=result_data,
            )

        except PermissionError:
            return ToolResult(
                success=False,
                error=f"Permission denied accessing: {request.base_path}",
                error_code=ToolErrorCode.PERMISSION_DENIED.value,
            )
        except Exception as e:
            return ToolResult(
                success=False, error=str(e), error_code=ToolErrorCode.EXECUTION_ERROR.value
            )

    @staticmethod
    def _build_glob_request(
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> _GlobRequest:
        return _GlobRequest(
            pattern=parameters["pattern"],
            base_path=resolve_path_from_workspace(
                parameters.get("path", "."),
                workspace=context.workspace,
                default=".",
            ),
            recursive=parameters.get("recursive", False),
            include_hidden=parameters.get("include_hidden", False),
            directories_only=parameters.get("directories_only", False),
            files_only=parameters.get("files_only", True),
            exclude_patterns=normalize_exclude_patterns(parameters.get("exclude")),
            max_results=parameters.get("max_results", 1000),
        )

    @staticmethod
    def _validate_base_path(base_path: str) -> ToolResult | None:
        if not os.path.exists(base_path):
            return ToolResult(
                success=False,
                error=f"Path not found: {base_path}",
                error_code=ToolErrorCode.PATH_NOT_FOUND.value,
            )

        if not os.path.isdir(base_path):
            return ToolResult(
                success=False,
                error=f"Path is not a directory: {base_path}",
                error_code=ToolErrorCode.NOT_A_DIRECTORY.value,
            )
        return None

    def _collect_matches(self, request: _GlobRequest) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        seen_paths: set[str] = set()
        for item in Path(request.base_path).glob(self._effective_pattern(request)):
            normalized_path = os.path.normpath(str(item))
            if normalized_path in seen_paths:
                continue
            seen_paths.add(normalized_path)
            match = self._project_match(request, normalized_path)
            if match is None:
                continue
            matches.append(match)
            if len(matches) >= request.max_results:
                break

        matches.sort(key=lambda x: x["modified"], reverse=True)
        return matches

    @staticmethod
    def _effective_pattern(request: _GlobRequest) -> str:
        use_recursive = request.recursive or "**" in request.pattern
        pattern_has_path = "/" in request.pattern or os.sep in request.pattern
        if use_recursive and "**" not in request.pattern and not pattern_has_path:
            return f"**/{request.pattern}"
        return request.pattern

    def _project_match(
        self,
        request: _GlobRequest,
        normalized_path: str,
    ) -> Dict[str, Any] | None:
        relative_path = self._relative_path(normalized_path, request.base_path)
        if not request.include_hidden and has_hidden_path_component(relative_path):
            return None
        if matches_exclude_path(relative_path, request.exclude_patterns):
            return None

        try:
            is_dir = os.path.isdir(normalized_path)
            is_file = os.path.isfile(normalized_path)
            if request.directories_only and not is_dir:
                return None
            if request.files_only and not is_file:
                return None

            stat = os.stat(normalized_path)
            return {
                "path": normalized_path,
                "name": os.path.basename(normalized_path),
                "is_file": is_file,
                "is_dir": is_dir,
                "size": stat.st_size if is_file else 0,
                "modified": stat.st_mtime,
            }
        except (PermissionError, OSError):
            return None

    @staticmethod
    def _relative_path(path: str, base_path: str) -> str:
        try:
            return os.path.relpath(path, base_path)
        except ValueError:
            return path

    @staticmethod
    def _build_result_data(
        request: _GlobRequest,
        matches: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        result_data: Dict[str, Any] = {
            "pattern": request.pattern,
            "base_path": request.base_path,
            "exclude": request.exclude_patterns,
            "matches": matches,
            "count": len(matches),
            "truncated": len(matches) >= request.max_results,
        }
        batch_hint = suggest_batch([item["path"] for item in matches if item.get("is_file")])
        if batch_hint:
            result_data["batch_hint"] = batch_hint
        return result_data
