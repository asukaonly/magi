"""
File edit tool - performs precise string replacement in files.
"""

import os
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from ..schema import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)
from ._edit_journal import record_edit_after, snapshot_before_edit
from ._read_constraint import require_prior_read

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import msvcrt

    def _lock_file(f):
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock_file(f):
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def _lock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)

    def _unlock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


# Maximum file size to edit (10MB)
MAX_FILE_SIZE = 10 * 1024 * 1024


@dataclass(frozen=True)
class _EditRequest:
    file_path: str
    old_string: str
    new_string: str
    replace_all: bool
    encoding: str


@dataclass(frozen=True)
class _ReplacementPlan:
    new_content: str
    replacements: int
    matched_lines: list[int]


def _file_edit_parameters() -> list[ToolParameter]:
    return [
        ToolParameter(
            name="path",
            type=ParameterType.STRING,
            description="The absolute path to the file to edit",
            required=True,
        ),
        ToolParameter(
            name="old_string",
            type=ParameterType.STRING,
            description=(
                "The text to replace. Must match exactly and be unique "
                "in the file (unless replace_all is true)"
            ),
            required=True,
        ),
        ToolParameter(
            name="new_string",
            type=ParameterType.STRING,
            description=("The text to replace with. Use empty string to delete the old_string"),
            required=True,
        ),
        ToolParameter(
            name="replace_all",
            type=ParameterType.BOOLEAN,
            description=(
                "Replace all occurrences of old_string. Default is false, "
                "which requires old_string to be unique"
            ),
            required=False,
            default=False,
        ),
        ToolParameter(
            name="encoding",
            type=ParameterType.STRING,
            description="File encoding",
            required=False,
            default="utf-8",
        ),
    ]


def _file_edit_examples() -> list[dict[str, Any]]:
    return [
        {
            "input": {
                "path": "/app/config.py",
                "old_string": "DEBUG = False",
                "new_string": "DEBUG = True",
            },
            "output": "Replaces the DEBUG setting in config.py",
        },
        {
            "input": {
                "path": "/app/main.py",
                "old_string": "old_function_name",
                "new_string": "new_function_name",
                "replace_all": True,
            },
            "output": "Renames function throughout the file",
        },
        {
            "input": {
                "path": "/app/temp.txt",
                "old_string": "line to remove\n",
                "new_string": "",
            },
            "output": "Deletes the specified line from the file",
        },
    ]


def _file_edit_metadata() -> dict[str, Any]:
    return {
        "task_intents": ["apply_change"],
        "domains": ["codebase", "config"],
        "operations": ["edit"],
        "query_shapes": ["targeted_patch", "exact_replacement"],
        "followed_by": ["file_read"],
        "avoid_task_intents": [
            "explore_codebase",
            "research_external",
            "clarify_requirement",
            "recall_context",
        ],
        "requires_known_target": True,
        "cost": "medium",
        "tool_hint": (
            "Use after reading the target slice and confirming the exact "
            "replacement; best for surgical in-place edits."
        ),
    }


def _edit_request(parameters: Dict[str, Any]) -> _EditRequest:
    return _EditRequest(
        file_path=parameters["path"],
        old_string=parameters["old_string"],
        new_string=parameters["new_string"],
        replace_all=parameters.get("replace_all", False),
        encoding=parameters.get("encoding", "utf-8"),
    )


def _error_result(error: str, error_code: ToolErrorCode) -> ToolResult:
    return ToolResult(success=False, error=error, error_code=error_code.value)


class FileEditTool(Tool):
    """
    File edit tool

    Performs precise string replacement in files with atomic writes and file locking.
    """

    def _init_schema(self) -> None:
        """Initialize schema"""
        self.schema = ToolSchema(
            name="file_edit",
            description="Edit file by replacing specific text. Use this for making targeted changes to files. The file must have been read with file_read in this session before editing.",
            category="file",
            version="1.1.0",
            author="Magi Team",
            parameters=_file_edit_parameters(),
            examples=_file_edit_examples(),
            timeout=10,
            retry_on_failure=False,
            dangerous=True,  # Editing files is a dangerous operation
            effect_class="local_write",
            effect_replay_policy="reconcilable",
            tags=["file", "edit", "io"],
            metadata=_file_edit_metadata(),
        )

    async def execute(
        self, parameters: Dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """Edit file by replacing text"""
        request = _edit_request(parameters)

        if not request.old_string:
            return _error_result(
                "old_string cannot be empty",
                ToolErrorCode.INVALID_PARAMETERS,
            )

        block_msg = require_prior_read(context, request.file_path)
        if block_msg is not None:
            return _error_result(block_msg, ToolErrorCode.INVALID_PARAMETERS)

        try:
            target_error = self._validate_edit_target(request)
            if target_error is not None:
                return target_error

            plan = self._build_replacement_plan(request)
            if isinstance(plan, ToolResult):
                return plan

            self._apply_replacement(context, request, plan)
            return ToolResult(success=True, data=self._result_data(request, plan))

        except PermissionError:
            return ToolResult(
                success=False,
                error=f"Permission denied editing file: {request.file_path}",
                error_code=ToolErrorCode.PERMISSION_DENIED.value,
            )
        except UnicodeDecodeError as e:
            return ToolResult(
                success=False,
                error=f"Failed to decode file with encoding {request.encoding}: {str(e)}",
                error_code=ToolErrorCode.DECODE_ERROR.value,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code=ToolErrorCode.WRITE_ERROR.value,
            )

    def _validate_edit_target(self, request: _EditRequest) -> ToolResult | None:
        if not os.path.exists(request.file_path):
            return _error_result(
                f"File not found: {request.file_path}",
                ToolErrorCode.FILE_NOT_FOUND,
            )

        if not os.path.isfile(request.file_path):
            return _error_result(
                f"Path is not a file: {request.file_path}",
                ToolErrorCode.NOT_A_FILE,
            )

        file_size = os.path.getsize(request.file_path)
        if file_size <= MAX_FILE_SIZE:
            return None

        return _error_result(
            (
                f"File too large ({file_size / 1024 / 1024:.1f}MB). "
                f"Maximum size is {MAX_FILE_SIZE / 1024 / 1024:.0f}MB."
            ),
            ToolErrorCode.INVALID_PARAMETERS,
        )

    def _build_replacement_plan(
        self,
        request: _EditRequest,
    ) -> _ReplacementPlan | ToolResult:
        normalized_old = self._normalize_line_endings(request.old_string)
        content, matched_lines = self._read_and_find(
            request.file_path,
            normalized_old,
            request.encoding,
        )
        occurrence_error = self._validate_occurrences(
            request,
            matched_lines,
        )
        if occurrence_error is not None:
            return occurrence_error
        return self._make_replacement_plan(
            request,
            content,
            normalized_old,
            matched_lines,
        )

    def _validate_occurrences(
        self,
        request: _EditRequest,
        matched_lines: list[int],
    ) -> ToolResult | None:
        occurrences = len(matched_lines)
        if occurrences == 0:
            return _error_result(
                f"Text not found in file: '{self._truncate_text(request.old_string, 50)}'",
                ToolErrorCode.INVALID_PARAMETERS,
            )

        if request.replace_all or occurrences <= 1:
            return None

        line_info = self._format_line_numbers(matched_lines)
        return _error_result(
            (
                f"Found {occurrences} occurrences at lines: {line_info}. "
                "Use replace_all=true to replace all, or provide a more "
                "specific old_string that is unique in the file."
            ),
            ToolErrorCode.INVALID_PARAMETERS,
        )

    def _make_replacement_plan(
        self,
        request: _EditRequest,
        content: str,
        normalized_old: str,
        matched_lines: list[int],
    ) -> _ReplacementPlan:
        if request.replace_all:
            return _ReplacementPlan(
                new_content=content.replace(normalized_old, request.new_string),
                replacements=len(matched_lines),
                matched_lines=matched_lines,
            )

        return _ReplacementPlan(
            new_content=content.replace(normalized_old, request.new_string, 1),
            replacements=1,
            matched_lines=matched_lines[:1],
        )

    def _apply_replacement(
        self,
        context: ToolExecutionContext,
        request: _EditRequest,
        plan: _ReplacementPlan,
    ) -> None:
        snapshot_ctx = snapshot_before_edit(context, request.file_path)
        self._atomic_write(request.file_path, plan.new_content, request.encoding)
        record_edit_after(context, request.file_path, snapshot_ctx, op="replace")

    def _result_data(
        self,
        request: _EditRequest,
        plan: _ReplacementPlan,
    ) -> dict[str, Any]:
        matched_lines: list[int | str]
        if len(plan.matched_lines) <= 10:
            matched_lines = plan.matched_lines
        else:
            matched_lines = plan.matched_lines[:10] + ["..."]

        return {
            "path": request.file_path,
            "replacements": plan.replacements,
            "matched_lines": matched_lines,
            "old_text_preview": self._truncate_text(request.old_string, 100),
            "new_text_preview": self._truncate_text(request.new_string, 100),
        }

    def _normalize_line_endings(self, text: str) -> str:
        """Normalize line endings to \n for consistent matching"""
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def _read_and_find(
        self, file_path: str, search_text: str, encoding: str
    ) -> Tuple[str, List[int]]:
        """
        Read file with exclusive lock and find all line numbers containing search_text.
        Returns (content, list of 1-based line numbers).
        """
        matched_lines: List[int] = []

        with open(file_path, "r", encoding=encoding, newline="") as f:
            _lock_file(f)

            try:
                content = f.read()

                # Normalize file content for matching
                normalized_content = self._normalize_line_endings(content)
                normalized_search = self._normalize_line_endings(search_text)

                # Find all occurrences with line numbers
                lines = normalized_content.split("\n")
                search_lines = normalized_search.split("\n")
                first_search_line = search_lines[0] if search_lines else ""

                for i, line in enumerate(lines, 1):
                    if first_search_line in line:
                        # Check if multi-line match starts here
                        if len(search_lines) == 1:
                            matched_lines.append(i)
                        else:
                            # Multi-line: verify full match
                            match = True
                            for j, search_line in enumerate(search_lines):
                                if i - 1 + j >= len(lines):
                                    match = False
                                    break
                                if search_line not in lines[i - 1 + j]:
                                    match = False
                                    break
                            if match:
                                matched_lines.append(i)

                return content, matched_lines
            finally:
                _unlock_file(f)

    def _atomic_write(self, file_path: str, content: str, encoding: str) -> None:
        """
        Write content to file atomically using temp file + rename.
        Also acquires exclusive lock during write.
        """
        dir_path = os.path.dirname(file_path) or "."

        # Create temp file in same directory for atomic rename
        fd, temp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")

        try:
            # Write to temp file
            with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
                _lock_file(f)
                try:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    _unlock_file(f)

            # Atomic rename
            os.replace(temp_path, file_path)
        except Exception:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    def _truncate_text(self, text: str, max_length: int) -> str:
        """Truncate text for preview, handling multiline"""
        if not text:
            return ""
        # Get first line
        first_line = text.split("\n")[0]
        if len(first_line) > max_length:
            return first_line[:max_length] + "..."
        if "\n" in text:
            return first_line + "..."
        return first_line

    def _format_line_numbers(self, lines: List[int]) -> str:
        """Format line numbers for display"""
        if len(lines) <= 5:
            return ", ".join(map(str, lines))
        return ", ".join(map(str, lines[:5])) + f" and {len(lines) - 5} more"
