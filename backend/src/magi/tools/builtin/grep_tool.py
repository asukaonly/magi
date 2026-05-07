"""
Grep tool - Search file contents using regex patterns
"""
import asyncio
import base64
import fnmatch
import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict

from magi.utils.packaged_paths import get_repo_root

from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType, ToolErrorCode
from ..utils.path_utils import (
    DEFAULT_EXCLUDE_PATTERNS,
    matches_exclude_path,
    normalize_exclude_patterns,
    resolve_path_from_workspace,
)


_RIPGREP_TIMEOUT_SECONDS = 30


def _ripgrep_executable_name() -> str:
    return "rg.exe" if os.name == "nt" else "rg"


def _platform_key() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def _architecture_key() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64", "x64"}:
        return "x64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    return machine or "unknown"


def _bundled_ripgrep_candidates() -> list[Path]:
    executable = _ripgrep_executable_name()
    platform_name = _platform_key()
    arch_name = _architecture_key()
    base = get_repo_root() / "runtime" / "bin" / "ripgrep"
    return [
        base / f"{platform_name}-{arch_name}" / executable,
        base / platform_name / executable,
        base / executable,
    ]


def _resolve_ripgrep_executable() -> str | None:
    """Return a bundled or system ripgrep executable path, if available."""
    for candidate in _bundled_ripgrep_candidates():
        if candidate.is_file():
            return str(candidate)

    for candidate in ("rg", "ripgrep"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""

    text = value.get("text")
    if isinstance(text, str):
        return text

    raw_bytes = value.get("bytes")
    if isinstance(raw_bytes, str):
        try:
            return base64.b64decode(raw_bytes).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - malformed tool output should not crash search
            return ""
    return ""


def _strip_line_end(value: str) -> str:
    return value.rstrip("\n\r")


def _matches_file_glob(relative_path: str, filename: str, file_pattern: str) -> bool:
    """Match file name/path against glob with basic ** compatibility."""
    pattern_has_path = "/" in file_pattern or os.sep in file_pattern
    normalized_file_pattern = file_pattern.replace(os.sep, "/")
    if not pattern_has_path:
        return fnmatch.fnmatch(filename, normalized_file_pattern)
    if fnmatch.fnmatch(relative_path, normalized_file_pattern):
        return True
    if "**/" in normalized_file_pattern:
        collapsed_pattern = normalized_file_pattern.replace("**/", "")
        if fnmatch.fnmatch(relative_path, collapsed_pattern):
            return True
    return False


def _ripgrep_glob_args(file_pattern: str, exclude_patterns: list[str]) -> list[str]:
    args: list[str] = []
    normalized_file_pattern = file_pattern.replace(os.sep, "/")
    if normalized_file_pattern and normalized_file_pattern != "*":
        args.extend(["--glob", normalized_file_pattern])
        if "**/" in normalized_file_pattern:
            args.extend(["--glob", normalized_file_pattern.replace("**/", "")])

    for raw_pattern in exclude_patterns:
        pattern = str(raw_pattern).strip().replace("\\", "/").strip("/")
        if not pattern:
            continue
        args.extend(["--glob", f"!{pattern}"])
        if "/" not in pattern:
            args.extend(["--glob", f"!**/{pattern}"])
            args.extend(["--glob", f"!**/{pattern}/**"])
    return args


def _build_result_data(
    *,
    pattern: str,
    search_path: str,
    file_pattern: str,
    exclude_patterns: list[str],
    matches: list[dict[str, Any]],
    files_searched: int,
    max_results: int,
    engine: str,
) -> dict[str, Any]:
    return {
        "pattern": pattern,
        "path": search_path,
        "glob": file_pattern,
        "exclude": exclude_patterns,
        "matches": matches,
        "match_count": len(matches),
        "files_searched": files_searched,
        "truncated": len(matches) >= max_results,
        "engine": engine,
    }


def _search_file_python(
    file_path: str,
    regex: re.Pattern[str],
    context_lines: int,
) -> list[dict[str, Any]]:
    file_matches: list[dict[str, Any]] = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as file_handle:
            lines = file_handle.readlines()

        for index, line in enumerate(lines):
            if regex.search(line):
                context_before: list[dict[str, Any]] = []
                context_after: list[dict[str, Any]] = []

                if context_lines > 0:
                    start = max(0, index - context_lines)
                    end = min(len(lines), index + context_lines + 1)
                    context_before = [
                        {"line_number": line_index + 1, "content": _strip_line_end(lines[line_index])}
                        for line_index in range(start, index)
                    ]
                    context_after = [
                        {"line_number": line_index + 1, "content": _strip_line_end(lines[line_index])}
                        for line_index in range(index + 1, end)
                    ]

                file_matches.append(
                    {
                        "file": file_path,
                        "line_number": index + 1,
                        "content": _strip_line_end(line),
                        "context_before": context_before,
                        "context_after": context_after,
                    }
                )
    except (PermissionError, UnicodeDecodeError, OSError):
        pass
    return file_matches


def _attach_context_lines(matches: list[dict[str, Any]], context_lines: int) -> None:
    if context_lines <= 0 or not matches:
        return

    matches_by_file: dict[str, list[dict[str, Any]]] = {}
    for match in matches:
        file_path = str(match.get("file", ""))
        if file_path:
            matches_by_file.setdefault(file_path, []).append(match)

    for file_path, file_matches in matches_by_file.items():
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as file_handle:
                lines = file_handle.readlines()
        except (PermissionError, UnicodeDecodeError, OSError):
            continue

        for match in file_matches:
            line_number = int(match.get("line_number", 0))
            index = line_number - 1
            if index < 0 or index >= len(lines):
                continue
            start = max(0, index - context_lines)
            end = min(len(lines), index + context_lines + 1)
            match["context_before"] = [
                {"line_number": line_index + 1, "content": _strip_line_end(lines[line_index])}
                for line_index in range(start, index)
            ]
            match["context_after"] = [
                {"line_number": line_index + 1, "content": _strip_line_end(lines[line_index])}
                for line_index in range(index + 1, end)
            ]


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
                    array_item_type=ParameterType.STRING,
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
            metadata={
                "task_intents": ["explore_codebase", "trace_implementation", "verify_source_claim"],
                "domains": ["codebase"],
                "operations": ["narrow", "verify"],
                "query_shapes": ["symbol_or_literal", "regex"],
                "followed_by": ["file_read"],
                "avoid_task_intents": ["research_external", "clarify_requirement", "recall_context"],
                "cost": "cheap",
                "tool_hint": "Use after narrowing scope to find symbols, strings, routes, flags, or config keys before confirming them in file_read.",
            },
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

            # Walk directory or search single file
            if os.path.isfile(search_path):
                relative_path = os.path.basename(search_path)
                if matches_exclude_path(relative_path, exclude_patterns):
                    return ToolResult(
                        success=True,
                        data=_build_result_data(
                            pattern=pattern,
                            search_path=search_path,
                            file_pattern=file_pattern,
                            exclude_patterns=exclude_patterns,
                            matches=[],
                            files_searched=0,
                            max_results=max_results,
                            engine="python",
                        ),
                    )

            ripgrep_result = await self._try_ripgrep_search(
                pattern=pattern,
                search_path=search_path,
                file_pattern=file_pattern,
                ignore_case=ignore_case,
                recursive=recursive,
                max_results=max_results,
                context_lines=context_lines,
                exclude_patterns=exclude_patterns,
            )
            if ripgrep_result is not None:
                return ToolResult(success=True, data=ripgrep_result)

            result_data = self._search_with_python(
                pattern=pattern,
                search_path=search_path,
                file_pattern=file_pattern,
                regex=regex,
                recursive=recursive,
                max_results=max_results,
                context_lines=context_lines,
                exclude_patterns=exclude_patterns,
            )

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

    async def _try_ripgrep_search(
        self,
        *,
        pattern: str,
        search_path: str,
        file_pattern: str,
        ignore_case: bool,
        recursive: bool,
        max_results: int,
        context_lines: int,
        exclude_patterns: list[str],
    ) -> dict[str, Any] | None:
        executable = _resolve_ripgrep_executable()
        if executable is None:
            return None

        argv = [
            executable,
            "--json",
            "--line-number",
            "--with-filename",
            "--color",
            "never",
            "--no-ignore",
        ]
        if ignore_case:
            argv.append("--ignore-case")
        if not recursive and os.path.isdir(search_path):
            argv.extend(["--max-depth", "1"])
        if os.path.isdir(search_path):
            argv.extend(_ripgrep_glob_args(file_pattern, exclude_patterns))
        argv.extend([pattern, search_path])

        matches: list[dict[str, Any]] = []
        matched_files: set[str] = set()
        files_searched = 0
        truncated = False

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError):
            return None

        assert process.stdout is not None
        stderr_task = asyncio.create_task(process.stderr.read() if process.stderr else _empty_bytes())

        try:
            while True:
                try:
                    raw_line = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=_RIPGREP_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    await _drain_bytes_task(stderr_task)
                    return None

                if not raw_line:
                    break

                try:
                    message = json.loads(raw_line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue

                message_type = message.get("type")
                data = message.get("data") if isinstance(message.get("data"), dict) else {}
                if message_type == "begin":
                    files_searched += 1
                    continue
                if message_type != "match":
                    continue

                path_text = _json_text(data.get("path"))
                line_text = _strip_line_end(_json_text(data.get("lines")))
                line_number = int(data.get("line_number") or 0)
                if not path_text or line_number <= 0:
                    continue
                normalized_path = os.path.normpath(path_text)
                matched_files.add(normalized_path)
                matches.append(
                    {
                        "file": normalized_path,
                        "line_number": line_number,
                        "content": line_text,
                        "context_before": [],
                        "context_after": [],
                    }
                )

                if len(matches) >= max_results:
                    truncated = True
                    process.terminate()
                    break

            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

            stderr = await stderr_task
            if process.returncode not in (0, 1) and not truncated:
                error_text = stderr.decode("utf-8", errors="replace").strip()
                if error_text:
                    return None

            _attach_context_lines(matches, context_lines)
            result_data = _build_result_data(
                pattern=pattern,
                search_path=search_path,
                file_pattern=file_pattern,
                exclude_patterns=exclude_patterns,
                matches=matches,
                files_searched=files_searched or len(matched_files),
                max_results=max_results,
                engine="ripgrep",
            )
            result_data["truncated"] = truncated or result_data["truncated"]
            return result_data
        except Exception:  # noqa: BLE001 - fall back to Python search on rg surprises
            if process.returncode is None:
                process.kill()
                await process.wait()
            await _drain_bytes_task(stderr_task)
            return None

    def _search_with_python(
        self,
        *,
        pattern: str,
        search_path: str,
        file_pattern: str,
        regex: re.Pattern[str],
        recursive: bool,
        max_results: int,
        context_lines: int,
        exclude_patterns: list[str],
    ) -> dict[str, Any]:
        matches: list[dict[str, Any]] = []
        files_searched = 0

        def append_file_matches(file_path: str) -> None:
            nonlocal files_searched
            if len(matches) >= max_results:
                return
            file_matches = _search_file_python(file_path, regex, context_lines)
            files_searched += 1
            for match in file_matches:
                if len(matches) >= max_results:
                    break
                matches.append(match)

        if os.path.isfile(search_path):
            append_file_matches(search_path)
        elif recursive:
            for root, dirs, files in os.walk(search_path):
                dirs[:] = [directory for directory in dirs if not directory.startswith(".")]
                relative_dirs = [
                    (directory, os.path.relpath(os.path.join(root, directory), search_path))
                    for directory in dirs
                ]
                dirs[:] = [
                    name
                    for name, relative_path in relative_dirs
                    if not matches_exclude_path(relative_path, exclude_patterns)
                ]

                for filename in files:
                    file_path = os.path.join(root, filename)
                    relative_path = os.path.relpath(file_path, search_path).replace(os.sep, "/")
                    if matches_exclude_path(relative_path, exclude_patterns):
                        continue
                    if not _matches_file_glob(relative_path, filename, file_pattern):
                        continue
                    append_file_matches(file_path)

                if len(matches) >= max_results:
                    break
        else:
            for item in os.listdir(search_path):
                file_path = os.path.join(search_path, item)
                relative_path = os.path.relpath(file_path, search_path).replace(os.sep, "/")
                if matches_exclude_path(relative_path, exclude_patterns):
                    continue
                if not _matches_file_glob(relative_path, item, file_pattern):
                    continue
                if os.path.isfile(file_path):
                    append_file_matches(file_path)
                if len(matches) >= max_results:
                    break

        return _build_result_data(
            pattern=pattern,
            search_path=search_path,
            file_pattern=file_pattern,
            exclude_patterns=exclude_patterns,
            matches=matches,
            files_searched=files_searched,
            max_results=max_results,
            engine="python",
        )


async def _empty_bytes() -> bytes:
    return b""


async def _drain_bytes_task(task: asyncio.Task[bytes]) -> bytes:
    try:
        return await task
    except Exception:  # noqa: BLE001 - best-effort cleanup before fallback
        return b""
