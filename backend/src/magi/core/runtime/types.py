"""
Runtime constants and agent identifiers.
"""

from enum import Enum

CHAT_AGENT_ID = "chat_agent"
MEMORY_DIGEST_AGENT_ID = "memory_digest_agent"
DAILY_REPORT_AGENT_ID = "daily_report_agent"


class TaskAgentType(str, Enum):
    """Supported task-agent categories."""

    CHAT = "chat"
    MEMORY_DIGEST = "memory_digest"
    DAILY_REPORT = "daily_report"


def build_task_agent_key(agent_type: TaskAgentType | str, agent_id: str) -> str:
    """Build stable runtime key for a task agent instance."""
    type_value = agent_type.value if isinstance(agent_type, TaskAgentType) else str(agent_type)
    return f"{type_value}:{agent_id}"
