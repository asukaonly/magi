"""Resolve structured task intent and tool hints for planning and tool selection."""

from __future__ import annotations

import json
from typing import Any, Optional

from .registry import ToolRegistry


class ToolHintResolver:
    """Infer task intent and rank tools with lightweight structured hints."""

    _WEB_TOOLS = {"web-search", "web-fetch"}
    _LOCAL_DISCOVERY_TOOLS = {"glob", "grep", "file_read"}

    _DEFAULT_TOOL_METADATA: dict[str, dict[str, Any]] = {
        "bash": {
            "task_intents": ["debug_runtime", "inspect_runtime_state"],
            "domains": ["runtime", "system"],
            "operations": ["probe", "inspect"],
            "query_shapes": ["shell_command", "one_off_check"],
            "followed_by": ["file_read", "file_edit"],
            "avoid_task_intents": ["research_external", "clarify_requirement", "recall_context"],
            "cost": "medium",
            "tool_hint": "Use for narrow executable checks, environment inspection, or reproducing a suspected behavior once the target is already known.",
        },
        "file_edit": {
            "task_intents": ["apply_change"],
            "domains": ["codebase", "config"],
            "operations": ["edit"],
            "query_shapes": ["targeted_patch", "exact_replacement"],
            "followed_by": ["file_read"],
            "avoid_task_intents": ["explore_codebase", "research_external", "clarify_requirement", "recall_context"],
            "requires_known_target": True,
            "cost": "medium",
            "tool_hint": "Use after reading the target slice and confirming the exact replacement; best for surgical in-place edits.",
        },
        "file_write": {
            "task_intents": ["apply_change", "create_artifact"],
            "domains": ["codebase", "docs"],
            "operations": ["edit", "create"],
            "query_shapes": ["new_file", "full_rewrite"],
            "followed_by": [],
            "avoid_task_intents": ["explore_codebase", "trace_implementation", "research_external", "clarify_requirement", "recall_context"],
            "requires_known_target": True,
            "cost": "medium",
            "tool_hint": "Use to create a new file or rewrite full contents once the destination path and content are already settled; prefer file_edit for precise edits.",
        },
        "glob": {
            "task_intents": ["explore_codebase", "trace_implementation"],
            "domains": ["codebase"],
            "operations": ["discover"],
            "query_shapes": ["path_or_module", "glob_pattern"],
            "followed_by": ["grep", "file_read"],
            "avoid_task_intents": ["research_external", "clarify_requirement", "recall_context"],
            "cost": "cheap",
            "tool_hint": "Use first to locate candidate files or folders from path or module clues before narrowing with grep or file_read.",
        },
        "grep": {
            "task_intents": ["explore_codebase", "trace_implementation", "verify_source_claim"],
            "domains": ["codebase"],
            "operations": ["narrow", "verify"],
            "query_shapes": ["symbol_or_literal", "regex"],
            "followed_by": ["file_read"],
            "avoid_task_intents": ["research_external", "clarify_requirement", "recall_context"],
            "cost": "cheap",
            "tool_hint": "Use after narrowing scope to find symbols, strings, routes, flags, or config keys before confirming them in file_read.",
        },
        "file_read": {
            "task_intents": ["trace_implementation", "verify_source_claim", "inspect_config"],
            "domains": ["codebase", "config"],
            "operations": ["verify", "inspect"],
            "query_shapes": ["exact_path", "focused_slice"],
            "followed_by": [],
            "avoid_task_intents": ["research_external", "clarify_requirement", "recall_context"],
            "requires_known_target": True,
            "cost": "medium",
            "tool_hint": "Use after glob or grep has narrowed the target; best for confirming the controlling code path or verifying a concrete claim from source.",
        },
        "agent": {
            "task_intents": ["delegate_task", "explore_codebase", "research_external"],
            "domains": ["orchestration", "codebase", "web"],
            "operations": ["delegate"],
            "query_shapes": ["multi_step_task", "parallelizable_research"],
            "followed_by": [],
            "avoid_task_intents": ["verify_source_claim"],
            "cost": "high",
            "tool_hint": "Use when the task is large enough to justify a worker, parallel exploration, or independent background execution; avoid for simple local checks.",
        },
        "memory_query": {
            "task_intents": ["recall_context"],
            "domains": ["memory"],
            "operations": ["recall", "verify"],
            "query_shapes": ["prior_session", "user_preference", "historical_fact"],
            "followed_by": [],
            "avoid_task_intents": ["explore_codebase", "research_external"],
            "cost": "medium",
            "tool_hint": "Use for prior conversations, preferences, historical actions, or learned procedures; prefer repo files for current code behavior.",
        },
        "ask_user_question": {
            "task_intents": ["clarify_requirement"],
            "domains": ["user"],
            "operations": ["clarify"],
            "query_shapes": ["blocking_decision", "missing_preference"],
            "followed_by": [],
            "avoid_task_intents": ["explore_codebase", "trace_implementation", "verify_source_claim", "research_external", "debug_runtime", "apply_change", "recall_context"],
            "blocks_on_user": True,
            "cost": "high",
            "tool_hint": "Use only when a missing user decision blocks safe progress or would likely cause rework.",
        },
        "system-settings": {
            "task_intents": ["inspect_config", "apply_change", "inspect_runtime_state"],
            "domains": ["config", "runtime"],
            "operations": ["inspect", "edit"],
            "query_shapes": ["config_path", "setting_value"],
            "followed_by": [],
            "avoid_task_intents": ["explore_codebase", "research_external", "clarify_requirement"],
            "cost": "cheap",
            "tool_hint": "Use to inspect or update Magi runtime and tool configuration; prefer source files when the question is about code behavior rather than live config.",
        },
        "web-search": {
            "task_intents": ["research_external"],
            "domains": ["web"],
            "operations": ["discover"],
            "query_shapes": ["topic_query", "time_bounded_query"],
            "followed_by": ["web-fetch"],
            "avoid_task_intents": ["verify_source_claim", "apply_change", "clarify_requirement"],
            "cost": "cheap",
            "tool_hint": "Use first for broad web discovery and source collection; follow with web-fetch only when article details or verification are needed.",
        },
        "web-fetch": {
            "task_intents": ["research_external", "verify_external_claim"],
            "domains": ["web"],
            "operations": ["fetch", "verify"],
            "query_shapes": ["exact_url"],
            "followed_by": [],
            "avoid_task_intents": ["explore_codebase", "clarify_requirement"],
            "requires_known_target": True,
            "cost": "medium",
            "tool_hint": "Use after web-search has identified candidate URLs and only when you need full-page details, verification, or source text.",
        },
    }

    _DETAIL_FETCH_KEYWORDS = (
        "详情",
        "展开",
        "全文",
        "原文",
        "核实",
        "verify",
        "交叉验证",
        "deep dive",
        "details",
    )

    _VERIFY_KEYWORDS = (
        "verify",
        "confirm",
        "exists",
        "whether",
        "有没有",
        "是否",
        "存在",
        "配置",
        "flag",
        "route",
        "symbol",
        "config",
        "key",
    )

    _MAP_SCOPE_KEYWORDS = (
        "architecture",
        "codebase",
        "repo",
        "目录结构",
        "项目架构",
        "代码架构",
        "代码库",
        "layout",
    )

    _TRACE_KEYWORDS = (
        "trace",
        "flow",
        "call chain",
        "execution",
        "bootstrap",
        "startup",
        "routing",
        "调用链",
        "链路",
        "流程",
        "执行",
        "路由",
    )

    _MEMORY_KEYWORDS = (
        "memory",
        "记忆",
        "偏好",
        "preference",
        "历史",
        "之前",
        "remember",
        "recall",
    )

    _CONFIG_KEYWORDS = (
        "config",
        "setting",
        "settings",
        "配置",
        "参数",
        "model",
        "provider",
        "api key",
    )

    _EDIT_REQUEST_PHRASES = (
        "fix ",
        "implement ",
        "update ",
        "change ",
        "edit ",
        "modify ",
        "refactor ",
        "add ",
        "please implement",
        "帮我实现",
        "实现一下",
        "改一下",
        "修一下",
        "修改",
        "修复",
        "新增",
        "重构",
    )

    _DEBUG_KEYWORDS = (
        "error",
        "报错",
        "timeout",
        "hang",
        "卡住",
        "heartbeat",
        "健康检查",
        "blocked",
        "stuck",
        "日志",
        "log",
    )

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._tool_registry = tool_registry

    def resolve(
        self,
        *,
        user_message: str,
        available_tools: list[str],
        request_profile: str | None = None,
        scope_hints: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        normalized_tools = [tool for tool in available_tools if self._get_tool_info(tool)]
        if not normalized_tools:
            return {}

        task_profile = self._infer_task_profile(
            user_message=user_message,
            request_profile=request_profile,
            scope_hints=scope_hints or [],
        )
        scope_policy = self._infer_scope_policy(
            user_message=user_message,
            request_profile=request_profile,
            scope_hints=scope_hints or [],
            available_tools=normalized_tools,
            task_profile=task_profile,
        )
        ranked_tools = self._rank_tools(task_profile=task_profile, available_tools=normalized_tools)
        return {
            "task_intent": task_profile["task_intent"],
            "domain": task_profile["domain"],
            "operation": task_profile["operation"],
            **scope_policy,
            "tool_hints": ranked_tools,
        }

    def render_guidance_block(self, hint: dict[str, Any] | None, *, heading: str = "Tool Guidance") -> str:
        if not isinstance(hint, dict) or not hint:
            return ""
        lines = [f"# {heading}"]
        task_intent = str(hint.get("task_intent") or "").strip()
        domain = str(hint.get("domain") or "").strip()
        operation = str(hint.get("operation") or "").strip()
        if task_intent:
            lines.append(f"Task intent: {task_intent}")
        if domain:
            lines.append(f"Domain: {domain}")
        if operation:
            lines.append(f"Operation: {operation}")
        target_locality = str(hint.get("target_locality") or "").strip()
        if target_locality:
            lines.append(f"Target locality: {target_locality}")
        preferred_resolution_order = str(hint.get("preferred_resolution_order") or "").strip()
        if preferred_resolution_order:
            lines.append(f"Preferred resolution order: {preferred_resolution_order}")
        if bool(hint.get("requires_clarification")):
            lines.append(
                "Clarification required before leaving the workspace when the target location is ambiguous."
            )
        tool_hints = hint.get("tool_hints")
        if isinstance(tool_hints, list) and tool_hints:
            lines.append("Preferred tool order:")
            for item in tool_hints[:3]:
                if not isinstance(item, dict):
                    continue
                tool_name = str(item.get("tool") or "").strip()
                reason = str(item.get("reason") or "").strip()
                if tool_name and reason:
                    lines.append(f"- {tool_name}: {reason}")
        lines.append("Structured hint JSON:")
        lines.append(json.dumps(hint, ensure_ascii=False))
        return "\n".join(lines)

    def _infer_task_profile(
        self,
        *,
        user_message: str,
        request_profile: str | None,
        scope_hints: list[str],
    ) -> dict[str, str]:
        lowered = str(user_message or "").lower()
        explicit_path = any("explicit path" in hint.lower() or "subdirectory" in hint.lower() for hint in scope_hints)
        if any(marker in user_message for marker in ["~/", "/", "\\", "src/", "backend/", "frontend/", "docs/"]):
            explicit_path = True
        if request_profile == "research":
            if any(keyword in lowered for keyword in self._DETAIL_FETCH_KEYWORDS):
                return {"task_intent": "research_external", "domain": "web", "operation": "fetch"}
            return {"task_intent": "research_external", "domain": "web", "operation": "discover"}
        if any(keyword in lowered for keyword in self._MEMORY_KEYWORDS):
            return {"task_intent": "recall_context", "domain": "memory", "operation": "recall"}
        if any(keyword in lowered for keyword in self._CONFIG_KEYWORDS):
            operation = "edit" if self._looks_like_edit_request(lowered) else "inspect"
            task_intent = "apply_change" if operation == "edit" else "inspect_config"
            return {"task_intent": task_intent, "domain": "config", "operation": operation}
        if any(keyword in lowered for keyword in self._DEBUG_KEYWORDS) and not explicit_path:
            return {"task_intent": "debug_runtime", "domain": "runtime", "operation": "probe"}
        if self._looks_like_edit_request(lowered):
            domain = "codebase" if explicit_path or any(token in lowered for token in ["code", "backend", "frontend", "repo", "module"]) else "config"
            return {"task_intent": "apply_change", "domain": domain, "operation": "edit"}
        if any(keyword in lowered for keyword in self._VERIFY_KEYWORDS):
            domain = "codebase" if explicit_path or any(token in lowered for token in ["backend", "frontend", "repo", "code", "module"]) else "runtime"
            task_intent = "verify_source_claim" if domain == "codebase" else "inspect_runtime_state"
            operation = "verify" if domain == "codebase" else "inspect"
            return {"task_intent": task_intent, "domain": domain, "operation": operation}
        if any(keyword in lowered for keyword in self._MAP_SCOPE_KEYWORDS):
            return {"task_intent": "explore_codebase", "domain": "codebase", "operation": "discover"}
        if any(keyword in lowered for keyword in self._TRACE_KEYWORDS):
            return {
                "task_intent": "trace_implementation",
                "domain": "codebase",
                "operation": "discover" if explicit_path else "narrow",
            }
        if explicit_path:
            return {"task_intent": "trace_implementation", "domain": "codebase", "operation": "discover"}
        return {"task_intent": "explore_codebase", "domain": "codebase", "operation": "discover"}

    def _infer_scope_policy(
        self,
        *,
        user_message: str,
        request_profile: str | None,
        scope_hints: list[str],
        available_tools: list[str],
        task_profile: dict[str, str],
    ) -> dict[str, Any]:
        explicit_path = self._has_explicit_path(user_message=user_message, scope_hints=scope_hints)
        has_web_tools = any(tool in self._WEB_TOOLS for tool in available_tools)
        has_local_discovery = any(tool in self._LOCAL_DISCOVERY_TOOLS for tool in available_tools)
        task_intent = str(task_profile.get("task_intent") or "").strip()
        domain = str(task_profile.get("domain") or "").strip()

        if explicit_path:
            return {
                "target_locality": "explicit_path",
                "preferred_resolution_order": "follow_explicit_path",
                "requires_clarification": False,
            }

        if request_profile == "research" and has_web_tools and has_local_discovery:
            return {
                "target_locality": "ambiguous_external_reference",
                "preferred_resolution_order": "ask_or_web_before_external_scan",
                "requires_clarification": True,
            }

        if request_profile == "research" or domain == "web":
            return {
                "target_locality": "web",
                "preferred_resolution_order": "web_first",
                "requires_clarification": False,
            }

        if task_intent in {"trace_implementation", "explore_codebase", "verify_source_claim", "apply_change"}:
            return {
                "target_locality": "workspace",
                "preferred_resolution_order": "workspace_first",
                "requires_clarification": False,
            }

        return {
            "target_locality": "workspace",
            "preferred_resolution_order": "workspace_first",
            "requires_clarification": False,
        }

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
        registry_lookup = getattr(self._tool_registry, "get_tool_info", None)
        if callable(registry_lookup):
            info = registry_lookup(tool_name)
            if isinstance(info, dict) and (info.get("metadata") or info.get("description") or info.get("parameters")):
                if not isinstance(info.get("metadata"), dict) and tool_name in self._DEFAULT_TOOL_METADATA:
                    info = {**info, "metadata": dict(self._DEFAULT_TOOL_METADATA[tool_name])}
                return info
        fallback_metadata = self._DEFAULT_TOOL_METADATA.get(tool_name)
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

    def _looks_like_edit_request(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in self._EDIT_REQUEST_PHRASES)

    @staticmethod
    def _has_explicit_path(*, user_message: str, scope_hints: list[str]) -> bool:
        if any("explicit path" in hint.lower() or "subdirectory" in hint.lower() for hint in scope_hints):
            return True
        return any(marker in user_message for marker in ["~/", "/", "\\", "src/", "backend/", "frontend/", "docs/"])