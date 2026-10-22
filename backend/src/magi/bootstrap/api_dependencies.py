"""Compose the API's explicit lifecycle collaborators."""
from __future__ import annotations

from ..api.runtime_dependencies import ApiRuntimeDependencies
from .context import RuntimeBootstrapContext


def build_api_runtime_dependencies(context: RuntimeBootstrapContext) -> ApiRuntimeDependencies:
    """Read live owners so startup, recovery and teardown cannot leave stale exports."""
    control = context.control_plane.module
    wiring = getattr(control, "wiring", None)
    return ApiRuntimeDependencies(
        outreach_service=context.outreach.service,
        plugin_user_content_clear=context.plugins.user_content_clear_coordinator,
        channels_module=context.channels.module,
        control_user_content_clear=getattr(wiring, "user_content_clear", None),
        chat_memory_projection_clear=context.chat.memory_projection_clear_lifecycle,
        self_memory=context.personality.self_memory,
        runtime_trace_store=context.runtime_trace.store,
        runtime_trace_subscriber=context.runtime_trace.subscriber,
        llm_usage_subscriber=context.llm.llm_usage_subscriber,
        llm_usage_store=context.llm.llm_usage_store,
        llm_adapter_ready=context.llm.llm_adapter is not None,
        full_clear_recovery_pending=context.runtime_commands.full_clear_recovery_pending,
    )
