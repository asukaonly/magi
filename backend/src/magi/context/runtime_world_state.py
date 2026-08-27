"""Canonical construction and rendering for host-owned runtime world state."""

from __future__ import annotations

import platform
from datetime import datetime

from ..utils.calendar_timezone import local_calendar_timezone_id
from ..utils.runtime import get_default_chat_workspace_path
from .schema import RuntimeSystemContext


def build_runtime_system_context(
    *,
    agent_id: str,
    agent_type: str,
    workspace_path: str | None = None,
) -> RuntimeSystemContext:
    """Capture the canonical runtime facts for one run at execution time."""

    now = datetime.now().astimezone()
    normalized_workspace_path = str(workspace_path or "").strip()
    return RuntimeSystemContext(
        current_date=now.date().isoformat(),
        timezone=local_calendar_timezone_id() or str(now.tzinfo or "unknown"),
        os_name=platform.system(),
        os_version=platform.release(),
        cwd=normalized_workspace_path or get_default_chat_workspace_path(),
        agent_id=str(agent_id or "unknown").strip() or "unknown",
        agent_type=str(agent_type or "unknown").strip() or "unknown",
    )


def render_runtime_world_state(runtime: RuntimeSystemContext) -> str:
    """Render a provider-neutral Runtime World State snapshot."""

    return "\n".join(
        [
            "# Runtime World State",
            f"* Local Date: {runtime.current_date}",
            f"* Timezone: {runtime.timezone}",
            f"* OS: {runtime.os_name} {runtime.os_version}",
            f"* Working Directory: {runtime.cwd}",
            f"* Agent: {runtime.agent_id} (type: {runtime.agent_type})",
        ]
    )


def build_runtime_world_state(
    *,
    agent_id: str,
    agent_type: str,
    workspace_path: str | None = None,
) -> str:
    """Build and render the canonical runtime snapshot for a model run."""

    return render_runtime_world_state(
        build_runtime_system_context(
            agent_id=agent_id,
            agent_type=agent_type,
            workspace_path=workspace_path,
        )
    )


__all__ = [
    "build_runtime_system_context",
    "build_runtime_world_state",
    "render_runtime_world_state",
]
