"""Messages API router facade."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..services import dispatch_user_message, get_chat_trace_read_service, get_runtime_system_status
from ...agent.runtime.types import TaskAgentType
from ...chat import (
    LocalChatAttachmentIngestionService,
    SessionWorkspaceUpdateResult,
    get_chat_read_service,
)
from ...chat.provider import get_chat_store
from ...core.runtime_bindings import require_agent_runtime
from ...personality.active_persona import get_current_personality
from ...personality.bootstrap_service import build_bootstrap_l2_priority_metadata
from .messages_common import (
    get_chat_attachment_ingestion_service as _get_chat_attachment_ingestion_service,
    get_default_chat_workspace_path as _get_default_chat_workspace_path,
    require_session_id as _require_session_id,
)
from .messages_content import (
    clear_conversation_history,
    get_chat_attachment_content,
    get_conversation_history,
    get_execution_trace,
    message_content_router,
    upload_chat_attachment,
)
from .messages_dispatch import (
    RUNTIME_NOT_READY,
    _ensure_runtime_ready_for_user_message,
    message_dispatch_router,
    send_user_message,
)
from .messages_models import (
    CancelSessionRunRequest,
    DetachSessionRunRequest,
    MessageLabelRequest,
    MessageResponse,
    RenameSessionRequest,
    UpdateSessionWorkspaceRequest,
    UserMessageRequest,
)
from .messages_mutations import delete_message, message_mutations_router, set_message_label
from .messages_run_control import cancel_session_run, detach_session_run, message_run_control_router
from .messages_sessions import (
    create_new_session,
    delete_session,
    list_sessions,
    message_sessions_router,
    rename_session,
    update_session_workspace,
)

user_messages_router = APIRouter()
user_messages_router.include_router(message_dispatch_router)
user_messages_router.include_router(message_content_router)
user_messages_router.include_router(message_sessions_router)
user_messages_router.include_router(message_run_control_router)
user_messages_router.include_router(message_mutations_router)

__all__ = [
    "APIRouter",
    "CancelSessionRunRequest",
    "DetachSessionRunRequest",
    "HTTPException",
    "LocalChatAttachmentIngestionService",
    "MessageLabelRequest",
    "MessageResponse",
    "RUNTIME_NOT_READY",
    "RenameSessionRequest",
    "SessionWorkspaceUpdateResult",
    "TaskAgentType",
    "UpdateSessionWorkspaceRequest",
    "UserMessageRequest",
    "_ensure_runtime_ready_for_user_message",
    "_get_chat_attachment_ingestion_service",
    "_get_default_chat_workspace_path",
    "_require_session_id",
    "build_bootstrap_l2_priority_metadata",
    "cancel_session_run",
    "clear_conversation_history",
    "create_new_session",
    "delete_message",
    "delete_session",
    "detach_session_run",
    "dispatch_user_message",
    "get_chat_attachment_content",
    "get_chat_read_service",
    "get_chat_store",
    "get_chat_trace_read_service",
    "get_conversation_history",
    "get_current_personality",
    "get_execution_trace",
    "get_runtime_system_status",
    "list_sessions",
    "rename_session",
    "require_agent_runtime",
    "send_user_message",
    "set_message_label",
    "update_session_workspace",
    "upload_chat_attachment",
    "user_messages_router",
]