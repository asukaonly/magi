"""Worker file-scan guardrails for function-calling execution."""

from __future__ import annotations

import os
from typing import Any

from ...chat.workspace import get_default_chat_workspace_path


def _resolve_default_chat_workspace_path() -> str:
    try:
        from . import function_calling as function_calling_module

        resolver = getattr(function_calling_module, "get_default_chat_workspace_path", None)
        if callable(resolver):
            return str(resolver())
    except Exception:
        pass
    return get_default_chat_workspace_path()


class FunctionCallingGuardrailsMixin:
    """Bound file-scan tools for worker planning and exploration loops."""

    _EXPLORE_EXCLUDE_PATTERNS = [
        "node_modules",
        "dist",
        "build",
        ".git",
        ".venv",
        "__pycache__",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "poetry.lock",
        "Pipfile.lock",
        "uv.lock",
        "bun.lockb",
    ]
    _FILE_SCAN_TOOLS = {"glob", "grep"}

    def _apply_worker_explore_guardrails(
        self,
        intent: str,
        tool_name: str,
        arguments: dict[str, Any],
        execution_workspace: str | None = None,
        user_message: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        """Apply strict guardrails for bounded scan-oriented workers."""
        safe_args = dict(arguments)
        if tool_name in self._FILE_SCAN_TOOLS:
            workspace_root = self._resolve_execution_workspace(execution_workspace)
            scan_root = self._resolve_scan_root_path(safe_args.get("path"), execution_workspace)
            if (
                intent not in {"worker_explore", "worker_plan"}
                and not self._path_within_root(scan_root, workspace_root)
                and not self._user_explicitly_targets_scan_path(
                    user_message=user_message,
                    path_value=safe_args.get("path"),
                    execution_workspace=execution_workspace,
                )
            ):
                return {}, (
                    "File scan guardrail: glob and grep must stay within the active workspace. "
                    f"Requested path resolves to {scan_root} while workspace is {workspace_root}. "
                    "Ask the user for an explicit path or use web-search first if the target may live outside the workspace."
                )

        if intent not in {"worker_explore", "worker_plan"}:
            return safe_args, None

        scan_label = "Explore" if intent == "worker_explore" else "Plan"
        if tool_name == "glob":
            pattern = str(safe_args.get("pattern", "")).strip()
            if not pattern:
                return {}, f"{scan_label} worker guardrail: glob pattern is required."
            if pattern in {"*", "**/*", "**"}:
                safe_args["pattern"] = "*"
                safe_args["recursive"] = False
            if "recursive" not in safe_args:
                safe_args["recursive"] = "**" in pattern
            if self._is_workspace_root_path(safe_args.get("path", "."), execution_workspace):
                safe_args["recursive"] = False
                if safe_args.get("pattern") in {"", "*", "**/*", "**"}:
                    safe_args["pattern"] = "*"
            safe_args["max_results"] = self._bounded_max_results(
                safe_args.get("max_results"),
                cap=200 if intent == "worker_explore" else 120,
            )
            safe_args["exclude"] = self._merge_exclude_patterns(safe_args.get("exclude"))
            return safe_args, None

        if tool_name == "grep":
            file_glob = str(safe_args.get("glob", "*")).strip()
            path_value = str(safe_args.get("path", ".")).strip()
            if file_glob in {"*", "**/*", "**"} and self._is_workspace_root_path(path_value, execution_workspace):
                return {}, (
                    f"{scan_label} worker guardrail: root-wide grep is blocked. "
                    "Use a scoped glob like frontend/**/*.ts or backend/**/*.py."
                )
            if "recursive" not in safe_args:
                safe_args["recursive"] = "**" in file_glob
            safe_args["max_results"] = self._bounded_max_results(
                safe_args.get("max_results"),
                cap=200 if intent == "worker_explore" else 120,
            )
            safe_args["exclude"] = self._merge_exclude_patterns(safe_args.get("exclude"))
            return safe_args, None

        return safe_args, None

    def _is_workspace_root_path(self, path_value: Any, execution_workspace: str | None) -> bool:
        """Return True when the requested path resolves to the active workspace root."""
        raw_path = "." if path_value is None else str(path_value).strip()
        if raw_path in {"", ".", "./"}:
            return True

        workspace_root = self._resolve_execution_workspace(execution_workspace)
        candidate_path = self._resolve_scan_root_path(raw_path, execution_workspace)
        return candidate_path == workspace_root

    def _resolve_scan_root_path(self, path_value: Any, execution_workspace: str | None) -> str:
        """Resolve the effective root path for glob/grep style scans."""
        workspace_root = self._resolve_execution_workspace(execution_workspace)
        raw_path = "." if path_value is None else str(path_value).strip()
        if raw_path in {"", ".", "./"}:
            return workspace_root

        expanded = os.path.expandvars(os.path.expanduser(raw_path))
        if os.path.isabs(expanded):
            return os.path.realpath(expanded)
        return os.path.realpath(os.path.join(workspace_root, expanded))

    @staticmethod
    def _path_within_root(candidate_path: str, root_path: str) -> bool:
        """Return True when ``candidate_path`` is equal to or nested under ``root_path``."""
        try:
            return os.path.commonpath([candidate_path, root_path]) == root_path
        except ValueError:
            return False

    def _user_explicitly_targets_scan_path(
        self,
        *,
        user_message: str | None,
        path_value: Any,
        execution_workspace: str | None,
    ) -> bool:
        """Return True when the user explicitly named the requested scan path."""
        normalized_message = str(user_message or "").strip()
        raw_path = str(path_value or "").strip()
        if not normalized_message or raw_path in {"", ".", "./"}:
            return False

        candidates = {
            raw_path,
            raw_path.rstrip("/"),
            os.path.expandvars(os.path.expanduser(raw_path)),
            os.path.expandvars(os.path.expanduser(raw_path)).rstrip("/"),
            self._resolve_scan_root_path(raw_path, execution_workspace),
            self._resolve_scan_root_path(raw_path, execution_workspace).rstrip("/"),
        }
        return any(candidate and candidate in normalized_message for candidate in candidates)

    def _resolve_execution_workspace(self, execution_workspace: str | None) -> str:
        raw_workspace = str(execution_workspace or "").strip() or _resolve_default_chat_workspace_path()
        return os.path.realpath(os.path.expandvars(os.path.expanduser(raw_workspace)))

    @staticmethod
    def _classify_guardrail_error_code(*, tool_name: str, error_text: str) -> str:
        if tool_name in {"glob", "grep"} and str(error_text or "").startswith("File scan guardrail:"):
            return "AMBIGUOUS_SCOPE"
        from ...tools.schema import ToolErrorCode

        return ToolErrorCode.INVALID_PARAMETERS.value

    @staticmethod
    def _bounded_max_results(value: Any, cap: int) -> int:
        """Parse max_results and keep it within [1, cap]."""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = cap
        return max(1, min(parsed, cap))

    def _merge_exclude_patterns(self, extra: Any) -> list[str]:
        """Merge caller exclude patterns with explore defaults."""
        merged: list[str] = []
        if isinstance(extra, list):
            for item in extra:
                value = str(item).strip()
                if value and value not in merged:
                    merged.append(value)
        for pattern in self._EXPLORE_EXCLUDE_PATTERNS:
            if pattern not in merged:
                merged.append(pattern)
        return merged
