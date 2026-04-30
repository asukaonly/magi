"""Tool ranking helpers for structured tool hints."""

from __future__ import annotations

from typing import Any


class ToolHintRankingMixin:
    """Rank available tools against an inferred task profile."""

    def _rank_tools(self, *, task_profile: dict[str, str], available_tools: list[str]) -> list[dict[str, Any]]:
        task_intent = str(task_profile.get("task_intent") or "").strip()
        domain = str(task_profile.get("domain") or "").strip()
        operation = str(task_profile.get("operation") or "").strip()
        ranked: list[tuple[float, dict[str, Any]]] = []
        for tool_name in available_tools:
            tool_info = self._get_tool_info(tool_name) or {}
            metadata = tool_info.get("metadata") if isinstance(tool_info.get("metadata"), dict) else {}
            task_intents = self._normalize_string_list(metadata.get("task_intents"))
            domains = self._normalize_string_list(metadata.get("domains"))
            operations = self._normalize_string_list(metadata.get("operations"))
            followed_by = self._normalize_string_list(metadata.get("followed_by"))
            avoid_task_intents = self._normalize_string_list(metadata.get("avoid_task_intents"))
            query_shapes = self._normalize_string_list(metadata.get("query_shapes"))
            requires_known_target = bool(metadata.get("requires_known_target", False))
            blocks_on_user = bool(metadata.get("blocks_on_user", False))
            cost = str(metadata.get("cost") or "").strip().lower()

            score = 0.0
            if task_intent in task_intents:
                score += 1.0
            if domain and domain in domains:
                score += 0.45
            if operation and operation in operations:
                score += 0.35
            if task_intent in avoid_task_intents:
                score -= 0.6
            if requires_known_target and operation in {"discover", "narrow", "probe"}:
                score -= 0.25
            if blocks_on_user and task_intent != "clarify_requirement":
                score -= 0.9
            if cost == "cheap":
                score += 0.1
            elif cost == "medium":
                score += 0.03
            elif cost == "high":
                score -= 0.05

            reason_parts: list[str] = []
            hint = str(metadata.get("tool_hint") or "").strip()
            if hint:
                reason_parts.append(hint)
            if domains:
                reason_parts.append(f"Domain: {', '.join(domains)}.")
            if operations:
                reason_parts.append(f"Operations: {', '.join(operations)}.")
            if query_shapes:
                reason_parts.append(f"Query shape: {', '.join(query_shapes)}.")
            if followed_by:
                reason_parts.append(f"Usually followed by: {', '.join(followed_by)}.")

            ranked.append(
                (
                    score,
                    {
                        "tool": tool_name,
                        "priority": 0,
                        "reason": " ".join(reason_parts).strip() or str(tool_info.get("description") or tool_name),
                        "task_intents": task_intents,
                        "domains": domains,
                        "operations": operations,
                        "followed_by": followed_by,
                    },
                )
            )

        ranked.sort(key=lambda item: item[0], reverse=True)
        results: list[dict[str, Any]] = []
        for index, (_, payload) in enumerate(ranked, start=1):
            payload["priority"] = index
            results.append(payload)
        return results

    def _get_tool_info(self, tool_name: str) -> dict[str, Any]:
        registry_lookup = getattr(self._tool_registry, "get_tool_info", None)  # type: ignore[attr-defined]
        if callable(registry_lookup):
            info = registry_lookup(tool_name)
            if isinstance(info, dict) and (info.get("metadata") or info.get("description") or info.get("parameters")):
                if not isinstance(info.get("metadata"), dict) and tool_name in self._DEFAULT_TOOL_METADATA:  # type: ignore[attr-defined]
                    info = {**info, "metadata": dict(self._DEFAULT_TOOL_METADATA[tool_name])}  # type: ignore[attr-defined]
                return info
        fallback_metadata = self._DEFAULT_TOOL_METADATA.get(tool_name)  # type: ignore[attr-defined]
        if fallback_metadata is None:
            return {}
        return {
            "name": tool_name,
            "description": "",
            "metadata": dict(fallback_metadata),
            "parameters": [],
        }

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text:
                normalized.append(text)
        return normalized


__all__ = ["ToolHintRankingMixin"]
