"""Tool-specific context formatting helpers for LLM tool messages."""

from __future__ import annotations

from typing import Any, Callable, Dict


class ToolContextFormatterRegistry:
    """Registry for tool-specific context formatters."""

    def __init__(self) -> None:
        self._formatters: dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}

    def register(
        self, tool_name: str, formatter: Callable[[Dict[str, Any]], Dict[str, Any]]
    ) -> None:
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

        def shell_formatter(data: Dict[str, Any]) -> Dict[str, Any]:
            return compact_shell_tool_data(data, max_text_chars=max_text_chars)

        registry.register("bash", shell_formatter)
        registry.register("powershell", shell_formatter)
        registry.register("grep", lambda data: compact_grep_tool_data(data, max_items=max_items))
        registry.register(
            "file_list", lambda data: compact_file_list_tool_data(data, max_items=max_items)
        )
        registry.register(
            "file_read",
            lambda data: compact_file_read_tool_data(data, max_text_chars=max_text_chars),
        )
        registry.register("agent", lambda data: compact_agent_tool_data(data, max_items=max_items))
        registry.register("memory_query", memory_formatter)
        registry.register("prepare_chat_attachments", compact_prepare_chat_attachments_tool_data)
        registry.register(
            "read_chat_attachment",
            lambda data: compact_read_chat_attachment_tool_data(
                data, max_text_chars=max_text_chars
            ),
        )
        registry.register(
            "web-search",
            lambda data: compact_web_search_tool_data(
                data,
                max_items=max_items,
                max_text_chars=max_text_chars,
            ),
        )
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


def compact_shell_tool_data(data: Dict[str, Any], *, max_text_chars: int) -> Dict[str, Any]:
    stdout = str(data.get("stdout", ""))
    stderr = str(data.get("stderr", ""))
    stdout_preview = stdout[-max_text_chars:] if max_text_chars > 0 else ""
    stderr_preview = stderr[-max_text_chars:] if max_text_chars > 0 else ""
    return {
        "command": data.get("command"),
        "return_code": data.get("return_code"),
        "stdout_preview": stdout_preview,
        "stdout_preview_truncated": len(stdout) > len(stdout_preview),
        "stdout_total_bytes": data.get("stdout_total_bytes"),
        "stdout_truncated": bool(data.get("stdout_truncated")),
        "stderr_preview": stderr_preview,
        "stderr_preview_truncated": len(stderr) > len(stderr_preview),
        "stderr_total_bytes": data.get("stderr_total_bytes"),
        "stderr_truncated": bool(data.get("stderr_truncated")),
        "timed_out": bool(data.get("timed_out")),
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


def compact_file_list_tool_data(data: Dict[str, Any], *, max_items: int) -> Dict[str, Any]:
    entries = data.get("entries")
    if not isinstance(entries, list):
        return data

    compact_entries = []
    for item in entries[:max_items]:
        if not isinstance(item, dict):
            continue
        compact_entries.append(
            {
                "name": item.get("name"),
                "relative_path": item.get("relative_path"),
                "kind": item.get("kind"),
                "is_dir": item.get("is_dir"),
                "size": item.get("size"),
                "depth": item.get("depth"),
            }
        )

    omitted = max(0, len(entries) - len(compact_entries))
    return {
        "path": data.get("path"),
        "recursive": data.get("recursive"),
        "count": data.get("count", len(entries)),
        "truncated": bool(data.get("truncated")) or omitted > 0,
        "omitted_entries": omitted,
        "entries": compact_entries,
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
    attachments = (
        data.get("chat_attachments") if isinstance(data.get("chat_attachments"), list) else []
    )
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


def compact_read_chat_attachment_tool_data(
    data: Dict[str, Any], *, max_text_chars: int
) -> Dict[str, Any]:
    text = str(data.get("text") or "")
    compact: Dict[str, Any] = {
        "attachment": data.get("attachment"),
        "content_kind": data.get("content_kind"),
        "offset": data.get("offset"),
        "returned_chars": data.get("returned_chars"),
        "total_chars": data.get("total_chars"),
        "is_complete": data.get("is_complete"),
        "next_offset": data.get("next_offset"),
        "parse_status": data.get("parse_status"),
        "page_count": data.get("page_count"),
        "summary": data.get("summary"),
    }
    if text:
        compact["text_preview"] = text[:max_text_chars]
        compact["text_truncated"] = len(text) > max_text_chars
    return compact


def compact_web_search_tool_data(
    data: Dict[str, Any],
    *,
    max_items: int,
    max_text_chars: int,
) -> Dict[str, Any]:
    results = data.get("results")
    compact: Dict[str, Any] = {
        "next_action": data.get("next_action"),
        "requested_provider": data.get("requested_provider"),
        "actual_provider": data.get("actual_provider") or data.get("provider"),
        "provider": data.get("provider"),
        "query": data.get("query"),
        "total": data.get("total"),
        "retryable": data.get("retryable"),
        "terminal": data.get("terminal"),
        "date_range_applied": data.get("date_range_applied"),
        "llm_guidance": data.get("llm_guidance"),
        "user_message_template": data.get("user_message_template"),
        "fallback_reason": data.get("fallback_reason"),
        "config_tool": data.get("config_tool"),
        "available_providers": data.get("available_providers"),
        "supported_providers": data.get("supported_providers"),
    }

    if isinstance(results, list):
        compact_results = []
        for item in results[:max_items]:
            if not isinstance(item, dict):
                continue
            compact_results.append(
                {
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "source": item.get("source"),
                    "description_preview": str(item.get("description", ""))[:max_text_chars],
                }
            )
        compact["result_count"] = len(results)
        compact["omitted_results"] = max(0, len(results) - len(compact_results))
        compact["results"] = compact_results

    return {key: value for key, value in compact.items() if value not in (None, [], {})}


def compact_image_generation_tool_data(data: Dict[str, Any]) -> Dict[str, Any]:
    attachments = (
        data.get("chat_attachments") if isinstance(data.get("chat_attachments"), list) else []
    )
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
