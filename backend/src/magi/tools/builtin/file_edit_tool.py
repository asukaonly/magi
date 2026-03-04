"""
File edit tool - performs precise string replacement in files.
"""
import os
import tempfile
import fcntl
from typing import Dict, Any, List, Tuple
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType, ToolErrorCode

# Maximum file size to edit (10MB)
MAX_FILE_SIZE = 10 * 1024 * 1024


class FileEditTool(Tool):
    """
    File edit tool

    Performs precise string replacement in files with atomic writes and file locking.
    """

    def _init_schema(self) -> None:
        """Initialize schema"""
        self.schema = ToolSchema(
            name="file_edit",
            description="Edit file by replacing specific text. Use this for making targeted changes to files.",
            category="file",
            version="1.1.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="path",
                    type=ParameterType.STRING,
                    description="The absolute path to the file to edit",
                    required=True,
                ),
                ToolParameter(
                    name="old_string",
                    type=ParameterType.STRING,
                    description="The text to replace. Must match exactly and be unique in the file (unless replace_all is true)",
                    required=True,
                ),
                ToolParameter(
                    name="new_string",
                    type=ParameterType.STRING,
                    description="The text to replace with. Use empty string to delete the old_string",
                    required=True,
                ),
                ToolParameter(
                    name="replace_all",
                    type=ParameterType.BOOLEAN,
                    description="Replace all occurrences of old_string. Default is false, which requires old_string to be unique",
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
            ],
            examples=[
                {
                    "input": {
                        "path": "/app/config.py",
                        "old_string": "DEBUG = False",
                        "new_string": "DEBUG = True"
                    },
                    "output": "Replaces the DEBUG setting in config.py",
                },
                {
                    "input": {
                        "path": "/app/main.py",
                        "old_string": "old_function_name",
                        "new_string": "new_function_name",
                        "replace_all": True
                    },
                    "output": "Renames function throughout the file",
                },
                {
                    "input": {
                        "path": "/app/temp.txt",
                        "old_string": "line to remove\n",
                        "new_string": ""
                    },
                    "output": "Deletes the specified line from the file",
                },
            ],
            timeout=10,
            retry_on_failure=False,
            dangerous=True,  # Editing files is a dangerous operation
            tags=["file", "edit", "io"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Edit file by replacing text"""
        file_path = parameters["path"]
        old_string = parameters["old_string"]
        new_string = parameters["new_string"]
        replace_all = parameters.get("replace_all", False)
        encoding = parameters.get("encoding", "utf-8")

        # Validate old_string is not empty
        if not old_string:
            return ToolResult(
                success=False,
                error="old_string cannot be empty",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value
            )

        try:
            # Check if file exists
            if not os.path.exists(file_path):
                return ToolResult(
                    success=False,
                    error=f"File not found: {file_path}",
                    error_code=ToolErrorCode.FILE_NOT_FOUND.value
                )

            # Check if it's a file (not directory)
            if not os.path.isfile(file_path):
                return ToolResult(
                    success=False,
                    error=f"Path is not a file: {file_path}",
                    error_code=ToolErrorCode.NOT_A_FILE.value
                )

            # Check file size
            file_size = os.path.getsize(file_path)
            if file_size > MAX_FILE_SIZE:
                return ToolResult(
                    success=False,
                    error=f"File too large ({file_size / 1024 / 1024:.1f}MB). Maximum size is {MAX_FILE_SIZE / 1024 / 1024:.0f}MB.",
                    error_code=ToolErrorCode.INVALID_PARAMETERS.value
                )

            # Normalize line endings in old_string for matching
            normalized_old = self._normalize_line_endings(old_string)

            # Read file with file lock
            content, matched_lines = self._read_and_find(file_path, normalized_old, encoding)

            occurrences = len(matched_lines)

            if occurrences == 0:
                return ToolResult(
                    success=False,
                    error=f"Text not found in file: '{self._truncate_text(old_string, 50)}'",
                    error_code=ToolErrorCode.INVALID_PARAMETERS.value
                )

            if not replace_all and occurrences > 1:
                line_info = self._format_line_numbers(matched_lines)
                return ToolResult(
                    success=False,
                    error=f"Found {occurrences} occurrences at lines: {line_info}. Use replace_all=true to replace all, or provide a more specific old_string that is unique in the file.",
                    error_code=ToolErrorCode.INVALID_PARAMETERS.value
                )

            # Perform replacement
            if replace_all:
                new_content = content.replace(normalized_old, new_string)
                replacements = occurrences
            else:
                new_content = content.replace(normalized_old, new_string, 1)
                replacements = 1
                matched_lines = matched_lines[:1]

            # Atomic write with file lock
            self._atomic_write(file_path, new_content, encoding)

            result_data = {
                "path": file_path,
                "replacements": replacements,
                "matched_lines": matched_lines if len(matched_lines) <= 10 else matched_lines[:10] + ["..."],
                "old_text_preview": self._truncate_text(old_string, 100),
                "new_text_preview": self._truncate_text(new_string, 100),
            }

            return ToolResult(
                success=True,
                data=result_data,
            )

        except PermissionError:
            return ToolResult(
                success=False,
                error=f"Permission denied editing file: {file_path}",
                error_code=ToolErrorCode.PERMISSION_DENIED.value
            )
        except UnicodeDecodeError as e:
            return ToolResult(
                success=False,
                error=f"Failed to decode file with encoding {encoding}: {str(e)}",
                error_code=ToolErrorCode.DECODE_ERROR.value
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code=ToolErrorCode.WRITE_ERROR.value
            )

    def _normalize_line_endings(self, text: str) -> str:
        """Normalize line endings to \n for consistent matching"""
        return text.replace('\r\n', '\n').replace('\r', '\n')

    def _read_and_find(self, file_path: str, search_text: str, encoding: str) -> Tuple[str, List[int]]:
        """
        Read file with exclusive lock and find all line numbers containing search_text.
        Returns (content, list of 1-based line numbers).
        """
        matched_lines: List[int] = []

        with open(file_path, "r", encoding=encoding, newline='') as f:
            # Acquire exclusive lock
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)

            try:
                content = f.read()

                # Normalize file content for matching
                normalized_content = self._normalize_line_endings(content)
                normalized_search = self._normalize_line_endings(search_text)

                # Find all occurrences with line numbers
                lines = normalized_content.split('\n')
                search_lines = normalized_search.split('\n')
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
                # Release lock
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _atomic_write(self, file_path: str, content: str, encoding: str) -> None:
        """
        Write content to file atomically using temp file + rename.
        Also acquires exclusive lock during write.
        """
        dir_path = os.path.dirname(file_path) or '.'

        # Create temp file in same directory for atomic rename
        fd, temp_path = tempfile.mkstemp(dir=dir_path, suffix='.tmp')

        try:
            # Write to temp file
            with os.fdopen(fd, 'w', encoding=encoding, newline='') as f:
                # Acquire exclusive lock on temp file
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())  # Ensure data is written to disk
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

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
        first_line = text.split('\n')[0]
        if len(first_line) > max_length:
            return first_line[:max_length] + "..."
        if '\n' in text:
            return first_line + "..."
        return first_line

    def _format_line_numbers(self, lines: List[int]) -> str:
        """Format line numbers for display"""
        if len(lines) <= 5:
            return ", ".join(map(str, lines))
        return ", ".join(map(str, lines[:5])) + f" and {len(lines) - 5} more"
