"""Tool-specific context formatting helpers for LLM tool messages."""

from __future__ import annotations

from typing import Any, Callable, Dict


class ToolContextFormatterRegistry:
    """Registry for tool-specific context formatters."""

    def __init__(self) -> None:
        self._formatters: dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}

    def register(self, tool_name: str, formatter: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        self._formatters[str(tool_name)] = formatter

    def get(self, tool_name: str) -> Callable[[Dict[str, Any]], Dict[str, Any]] | None:
        return self._formatters.get(tool_name)

    @classmethod
    def build_default(
        cls,
        *,
        max_items: int,
        max_text_chars: int,
        memory_formatter: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> "ToolContextFormatterRegistry":
        registry = cls()
        registry.register("glob", lambda data: compact_glob_tool_data(data, max_items=max_items))
        registry.register("bash", lambda data: compact_bash_tool_data(data, max_text_chars=max_text_chars))
        registry.register("grep", lambda data: compact_grep_tool_data(data, max_items=max_items))
        registry.register("file_read", lambda data: compact_file_read_tool_data(data, max_text_chars=max_text_chars))
        registry.register("agent", lambda data: compact_agent_tool_data(data, max_items=max_items))
        registry.register("memory_query", memory_formatter)
        registry.register("prepare_chat_attachments", compact_prepare_chat_attachments_tool_data)
        registry.register("image-generation", compact_image_generation_tool_data)
        registry.register("image_generation", compact_image_generation_tool_data)
        return registry


def compact_glob_tool_data(data: Dict[str, Any], *, max_items: int) -> Dict[str, Any]:
    matches = data.get("matches")
    if not isinstance(matches, list):
        return data

    limited = matches[:max_items]
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


def compact_bash_tool_data(data: Dict[str, Any], *, max_text_chars: int) -> Dict[str, Any]:
    stdout = str(data.get("stdout", ""))
    stderr = str(data.get("stderr", ""))
    return {
        "command": data.get("command"),
        "return_code": data.get("return_code"),
        "stdout_preview": stdout[:max_text_chars],
        "stdout_truncated": len(stdout) > max_text_chars,
        "stderr_preview": stderr[:max_text_chars],
        "stderr_truncated": len(stderr) > max_text_chars,
    }


def compact_grep_tool_data(data: Dict[str, Any], *, max_items: int) -> Dict[str, Any]:
    matches = data.get("matches")
    if not isinstance(matches, list):
        return data

    compact_matches = []
    for item in matches[:max_items]:
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


def compact_file_read_tool_data(data: Dict[str, Any], *, max_text_chars: int) -> Dict[str, Any]:
    content = str(data.get("content", ""))
    return {
        "path": data.get("path"),
        "encoding": data.get("encoding"),
        "size": data.get("size"),
        "total_size": data.get("total_size"),
        "is_complete": data.get("is_complete"),
        "content_preview": content[:max_text_chars],
        "content_truncated": len(content) > max_text_chars,
    }


def compact_agent_tool_data(data: Dict[str, Any], *, max_items: int) -> Dict[str, Any]:
    workers = data.get("workers")
    if isinstance(workers, list):
        compact = {
            "worker_count": len(workers),
            "workers": [
                compact_agent_tool_data(item, max_items=max_items)
                for item in workers[:max_items]
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

    return {
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


def compact_prepare_chat_attachments_tool_data(data: Dict[str, Any]) -> Dict[str, Any]:
    attachments = data.get("chat_attachments") if isinstance(data.get("chat_attachments"), list) else []
    return {
        "prepared_count": len(attachments),
        "attachments": [
            {
                "attachment_id": item.get("attachment_id"),
                "kind": item.get("kind"),
                "original_name": item.get("original_name"),
                "size_bytes": item.get("size_bytes"),
            }
            for item in attachments
            if isinstance(item, dict)
        ],
        "summary": data.get("summary"),
    }


def compact_image_generation_tool_data(data: Dict[str, Any]) -> Dict[str, Any]:
    attachments = data.get("chat_attachments") if isinstance(data.get("chat_attachments"), list) else []
    artifacts = data.get("artifacts") if isinstance(data.get("artifacts"), list) else []
    paths = data.get("paths") if isinstance(data.get("paths"), list) else []
    generated_count = len(artifacts) or len(attachments) or len(paths)
    payload: Dict[str, Any] = {
        "generated_count": generated_count,
        "model": data.get("model"),
        "summary": data.get("message") or data.get("summary"),
    }
    if attachments:
        payload["attachments"] = [
            {
                "attachment_id": item.get("attachment_id"),
                "kind": item.get("kind"),
                "original_name": item.get("original_name"),
                "size_bytes": item.get("size_bytes"),
            }
            for item in attachments
            if isinstance(item, dict)
        ]
        payload["display_guidance"] = (
            "Generated images are attached to the assistant reply; do not print local filesystem paths unless asked."
        )
    elif paths:
        payload["paths"] = paths[:3]
    return payload
