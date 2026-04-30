"""Task profile and scope policy inference for tool hints."""

from __future__ import annotations

from typing import Any


class ToolHintProfileMixin:
    """Infer task intent/domain/operation and target locality."""

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
            if any(keyword in lowered for keyword in self._DETAIL_FETCH_KEYWORDS):  # type: ignore[attr-defined]
                return {"task_intent": "research_external", "domain": "web", "operation": "fetch"}
            return {"task_intent": "research_external", "domain": "web", "operation": "discover"}
        if any(keyword in lowered for keyword in self._MEMORY_KEYWORDS):  # type: ignore[attr-defined]
            return {"task_intent": "recall_context", "domain": "memory", "operation": "recall"}
        if any(keyword in lowered for keyword in self._CONFIG_KEYWORDS):  # type: ignore[attr-defined]
            operation = "edit" if self._looks_like_edit_request(lowered) else "inspect"
            task_intent = "apply_change" if operation == "edit" else "inspect_config"
            return {"task_intent": task_intent, "domain": "config", "operation": operation}
        if any(keyword in lowered for keyword in self._DEBUG_KEYWORDS) and not explicit_path:  # type: ignore[attr-defined]
            return {"task_intent": "debug_runtime", "domain": "runtime", "operation": "probe"}
        if self._looks_like_edit_request(lowered):
            domain = "codebase" if explicit_path or any(token in lowered for token in ["code", "backend", "frontend", "repo", "module"]) else "config"
            return {"task_intent": "apply_change", "domain": domain, "operation": "edit"}
        if any(keyword in lowered for keyword in self._VERIFY_KEYWORDS):  # type: ignore[attr-defined]
            domain = "codebase" if explicit_path or any(token in lowered for token in ["backend", "frontend", "repo", "code", "module"]) else "runtime"
            task_intent = "verify_source_claim" if domain == "codebase" else "inspect_runtime_state"
            operation = "verify" if domain == "codebase" else "inspect"
            return {"task_intent": task_intent, "domain": domain, "operation": operation}
        if any(keyword in lowered for keyword in self._MAP_SCOPE_KEYWORDS):  # type: ignore[attr-defined]
            return {"task_intent": "explore_codebase", "domain": "codebase", "operation": "discover"}
        if any(keyword in lowered for keyword in self._TRACE_KEYWORDS):  # type: ignore[attr-defined]
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
        has_web_tools = any(tool in self._WEB_TOOLS for tool in available_tools)  # type: ignore[attr-defined]
        has_local_discovery = any(tool in self._LOCAL_DISCOVERY_TOOLS for tool in available_tools)  # type: ignore[attr-defined]
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

    def _looks_like_edit_request(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in self._EDIT_REQUEST_PHRASES)  # type: ignore[attr-defined]

    @staticmethod
    def _has_explicit_path(*, user_message: str, scope_hints: list[str]) -> bool:
        if any("explicit path" in hint.lower() or "subdirectory" in hint.lower() for hint in scope_hints):
            return True
        return any(marker in user_message for marker in ["~/", "/", "\\", "src/", "backend/", "frontend/", "docs/"])


__all__ = ["ToolHintProfileMixin"]
