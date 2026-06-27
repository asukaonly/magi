"""Messages API router facade."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

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
    "MessageLabelRequest",
    "MessageResponse",
    "RUNTIME_NOT_READY",
    "RenameSessionRequest",
    "UpdateSessionWorkspaceRequest",
    "UserMessageRequest",
    "_ensure_runtime_ready_for_user_message",
    "cancel_session_run",
    "clear_conversation_history",
    "create_new_session",
    "delete_message",
    "delete_session",
    "detach_session_run",
    "get_chat_attachment_content",
    "get_conversation_history",
    "get_execution_trace",
    "list_sessions",
    "rename_session",
    "send_user_message",
    "set_message_label",
    "update_session_workspace",
    "upload_chat_attachment",
    "user_messages_router",
]
