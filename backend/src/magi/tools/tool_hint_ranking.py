"""Tool ranking helpers for structured tool hints."""

from __future__ import annotations

from typing import Any


class ToolHintRankingMixin:
    """Rank available tools against an inferred task profile."""

    def _rank_tools(self, *, task_profile: dict[str, str], available_tools: list[str]) -> list[dict[str, Any]]:
        profile = self._normalized_task_profile(task_profile)
        ranked: list[tuple[float, dict[str, Any]]] = []
        for tool_name in available_tools:
            ranked.append(self._rank_tool(tool_name=tool_name, profile=profile))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return self._with_priorities(ranked)

    @staticmethod
    def _normalized_task_profile(task_profile: dict[str, str]) -> dict[str, str]:
        return {
            "task_intent": str(task_profile.get("task_intent") or "").strip(),
            "domain": str(task_profile.get("domain") or "").strip(),
            "operation": str(task_profile.get("operation") or "").strip(),
        }

    def _rank_tool(
        self,
        *,
        tool_name: str,
        profile: dict[str, str],
    ) -> tuple[float, dict[str, Any]]:
        tool_info = self._get_tool_info(tool_name) or {}
        metadata = self._tool_metadata(tool_info)
        facets = self._tool_metadata_facets(metadata)
        score = self._tool_score(metadata=metadata, facets=facets, profile=profile)
        return score, self._tool_rank_payload(
            tool_name=tool_name,
            tool_info=tool_info,
            metadata=metadata,
            facets=facets,
        )

    @staticmethod
    def _tool_metadata(tool_info: dict[str, Any]) -> dict[str, Any]:
        metadata = tool_info.get("metadata")
        return metadata if isinstance(metadata, dict) else {}

    def _tool_metadata_facets(self, metadata: dict[str, Any]) -> dict[str, list[str]]:
        return {
            "task_intents": self._normalize_string_list(metadata.get("task_intents")),
            "domains": self._normalize_string_list(metadata.get("domains")),
            "operations": self._normalize_string_list(metadata.get("operations")),
            "followed_by": self._normalize_string_list(metadata.get("followed_by")),
            "avoid_task_intents": self._normalize_string_list(metadata.get("avoid_task_intents")),
            "query_shapes": self._normalize_string_list(metadata.get("query_shapes")),
        }

    @staticmethod
    def _tool_score(
        *,
        metadata: dict[str, Any],
        facets: dict[str, list[str]],
        profile: dict[str, str],
    ) -> float:
        score = 0.0
        if profile["task_intent"] in facets["task_intents"]:
            score += 1.0
        if profile["domain"] and profile["domain"] in facets["domains"]:
            score += 0.45
        if profile["operation"] and profile["operation"] in facets["operations"]:
            score += 0.35
        if profile["task_intent"] in facets["avoid_task_intents"]:
            score -= 0.6
        if bool(metadata.get("requires_known_target", False)) and profile["operation"] in {"discover", "narrow", "probe"}:
            score -= 0.25
        if bool(metadata.get("blocks_on_user", False)) and profile["task_intent"] != "clarify_requirement":
            score -= 0.9
        cost = str(metadata.get("cost") or "").strip().lower()
        if cost == "cheap":
            score += 0.1
        elif cost == "medium":
            score += 0.03
        elif cost == "high":
            score -= 0.05
        return score

    def _tool_rank_payload(
        self,
        *,
        tool_name: str,
        tool_info: dict[str, Any],
        metadata: dict[str, Any],
        facets: dict[str, list[str]],
    ) -> dict[str, Any]:
        return {
            "tool": tool_name,
            "priority": 0,
            "reason": self._tool_reason(tool_name=tool_name, tool_info=tool_info, metadata=metadata, facets=facets),
            "task_intents": facets["task_intents"],
            "domains": facets["domains"],
            "operations": facets["operations"],
            "followed_by": facets["followed_by"],
        }

    @staticmethod
    def _tool_reason(
        *,
        tool_name: str,
        tool_info: dict[str, Any],
        metadata: dict[str, Any],
        facets: dict[str, list[str]],
    ) -> str:
        reason_parts: list[str] = []
        hint = str(metadata.get("tool_hint") or "").strip()
        if hint:
            reason_parts.append(hint)
        if facets["domains"]:
            reason_parts.append(f"Domain: {', '.join(facets['domains'])}.")
        if facets["operations"]:
            reason_parts.append(f"Operations: {', '.join(facets['operations'])}.")
        if facets["query_shapes"]:
            reason_parts.append(f"Query shape: {', '.join(facets['query_shapes'])}.")
        if facets["followed_by"]:
            reason_parts.append(f"Usually followed by: {', '.join(facets['followed_by'])}.")
        return " ".join(reason_parts).strip() or str(tool_info.get("description") or tool_name)

    @staticmethod
    def _with_priorities(ranked: list[tuple[float, dict[str, Any]]]) -> list[dict[str, Any]]:
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
                return info
        return {}

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
