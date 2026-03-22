"""
Postprocessing helpers for function-calling loop.

This module keeps tool-result context shaping out of executor orchestration logic.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from ...memory.tool_context_formatter import compact_memory_tool_data


class FunctionCallingPostprocessor:
    """Build compact tool payloads for function-calling contexts."""

    def __init__(
        self,
        max_items: int = 40,
        max_text_chars: int = 2000,
    ) -> None:
        self.max_items = max_items
        self.max_text_chars = max_text_chars
        self._tool_compactors: dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            "glob": self._compact_glob_data,
            "bash": self._compact_bash_data,
            "grep": self._compact_grep_data,
            "file_read": self._compact_file_read_data,
            "agent": self._compact_agent_data,
            "memory_query": self._compact_memory_query_data,
        }

    def build_tool_message_payload(self, tool_name: str, result: Any) -> Dict[str, Any]:
        """Build compact tool result payload for the next LLM turn."""
        payload = {
            "success": bool(getattr(result, "success", False)),
            "data": self._compact_tool_data_for_context(
                tool_name=tool_name, data=getattr(result, "data", None)
            ),
            "error": getattr(result, "error", None),
        }
        if tool_name == "memory_query":
            payload.update(
                {
                    "source_of_truth_for_turn": True,
                    "context_role": "historical_recall_result",
                    "usage_guidance": (
                        "Treat memory_query results as the source of truth for historical recall in this turn. "
                        "Do not replace missing recall results with implicit memory or guesses."
                    ),
                }
            )
        return payload

    def _compact_tool_data_for_context(self, tool_name: str, data: Any) -> Any:
        """Trim large tool payloads before injecting back into model context."""
        if not isinstance(data, dict):
            return data

        compactor = self._tool_compactors.get(tool_name)
        if compactor is not None:
            return compactor(data)

        return data

    def _compact_memory_query_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return compact_memory_tool_data(
            data,
            max_items=self.max_items,
            max_text_chars=self.max_text_chars,
        )

    def _compact_glob_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        matches = data.get("matches")
        if not isinstance(matches, list):
            return data

        limited = matches[: self.max_items]
        compact_matches = []
        for item in limited:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if not path:
                continue
            compact_matches.append(
                {
                    "path": path,
                    "name": item.get("name"),
                    "type": "dir" if item.get("is_dir") else "file",
                }
            )

        omitted = max(0, len(matches) - len(compact_matches))
        return {
            "pattern": data.get("pattern"),
            "base_path": data.get("base_path"),
            "count": data.get("count", len(matches)),
            "truncated": bool(data.get("truncated")) or omitted > 0,
            "omitted_matches": omitted,
            "matches": compact_matches,
        }

    def _compact_bash_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        stdout = str(data.get("stdout", ""))
        stderr = str(data.get("stderr", ""))
        return {
            "command": data.get("command"),
            "return_code": data.get("return_code"),
            "stdout_preview": stdout[: self.max_text_chars],
            "stdout_truncated": len(stdout) > self.max_text_chars,
            "stderr_preview": stderr[: self.max_text_chars],
            "stderr_truncated": len(stderr) > self.max_text_chars,
        }

    def _compact_grep_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        matches = data.get("matches")
        if not isinstance(matches, list):
            return data

        compact_matches = []
        for item in matches[: self.max_items]:
            if not isinstance(item, dict):
                continue
            compact_matches.append(
                {
                    "file": item.get("file"),
                    "line_number": item.get("line_number"),
                    "content_preview": str(item.get("content", ""))[:200],
                }
            )

        omitted = max(0, len(matches) - len(compact_matches))
        return {
            "pattern": data.get("pattern"),
            "path": data.get("path"),
            "glob": data.get("glob"),
            "match_count": data.get("match_count", len(matches)),
            "files_searched": data.get("files_searched"),
            "truncated": bool(data.get("truncated")) or omitted > 0,
            "omitted_matches": omitted,
            "matches": compact_matches,
        }

    def _compact_file_read_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        content = str(data.get("content", ""))
        return {
            "path": data.get("path"),
            "encoding": data.get("encoding"),
            "size": data.get("size"),
            "total_size": data.get("total_size"),
            "is_complete": data.get("is_complete"),
            "content_preview": content[: self.max_text_chars],
            "content_truncated": len(content) > self.max_text_chars,
        }

    def _compact_agent_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        workers = data.get("workers")
        if isinstance(workers, list):
            compact = {
                "worker_count": len(workers),
                "workers": [
                    self._compact_agent_data(item)
                    for item in workers[: self.max_items]
                    if isinstance(item, dict)
                ],
            }
            if "worker_ids" in data:
                compact["worker_ids"] = data.get("worker_ids")
            if "orchestration_id" in data:
                compact["orchestration_id"] = data.get("orchestration_id")
            if "status" in data:
                compact["status"] = data.get("status")
            if "missing_worker_ids" in data:
                compact["missing_worker_ids"] = data.get("missing_worker_ids")
            if "run_in_background" in data:
                compact["run_in_background"] = data.get("run_in_background")
            if "parallel" in data:
                compact["parallel"] = data.get("parallel")
            return compact

        if "worker_ids" in data and "worker_count" in data:
            return {
                "worker_count": data.get("worker_count"),
                "worker_ids": data.get("worker_ids"),
                "orchestration_id": data.get("orchestration_id"),
                "status": data.get("status"),
                "run_in_background": data.get("run_in_background"),
                "parallel": data.get("parallel"),
            }

        compact = {
            "worker_id": data.get("worker_id"),
            "status": data.get("status"),
            "subagent_type": data.get("subagent_type"),
            "description": data.get("description"),
            "orchestration_id": data.get("orchestration_id"),
            "subtask_id": data.get("subtask_id"),
            "worker_result": data.get("result") if isinstance(data.get("result"), dict) else None,
            "error": data.get("error"),
            "failure_reason": data.get("failure_reason"),
            "needs_await": data.get("status") == "running",
        }
        return compact
