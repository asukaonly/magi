"""Chat capability bindings consumed by channel adapters."""
from magi.core.container import require_binding


def require_chat_read_service():
    return require_binding("chat_read_service")


def require_user_message_dispatcher():
    return require_binding("user_message_dispatcher")
