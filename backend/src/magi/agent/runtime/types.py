"""Runtime constants and agent identifiers."""

from enum import Enum

CHAT_AGENT_ID = "chat_agent"


class TaskAgentType(str, Enum):
    """Supported task-agent categories."""

    CHAT = "chat"
    TIMELINE = "timeline"


def get_task_agent_type_value(agent_type: TaskAgentType | str) -> str:
    """Normalize task-agent type to plain string value."""
    return agent_type.value if isinstance(agent_type, TaskAgentType) else str(agent_type)


def build_task_agent_key(agent_type: TaskAgentType | str, agent_id: str) -> str:
    """Build stable runtime key for a task agent instance."""
    return f"{get_task_agent_type_value(agent_type)}:{agent_id}"
