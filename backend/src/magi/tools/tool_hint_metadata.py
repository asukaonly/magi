"""Static metadata and keyword sets for tool hint resolution."""

from __future__ import annotations


class ToolHintMetadataMixin:
    """Shared tool hint metadata and classifier keyword sets."""

    _WEB_TOOLS = {"web-search", "web-fetch"}
    _LOCAL_DISCOVERY_TOOLS = {"glob", "grep", "file_read"}

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
