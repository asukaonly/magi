"""Static metadata and keyword sets for tool hint resolution."""

from __future__ import annotations

from typing import Any


class ToolHintMetadataMixin:
    """Shared tool hint metadata and classifier keyword sets."""

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


__all__ = ["ToolHintMetadataMixin"]
