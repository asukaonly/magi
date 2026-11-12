"""Known semantic failures preserved across storage implementations."""

from .storage import StorageResult
from .storage_models.channels import OutreachIntentConflictError
from .storage_models.chat_errors import ChatMessageConflictError, ChatTurnConflictError
from .storage_models.chat_session_errors import ChatSessionCreationConflict, ChatSessionNotFound
from .storage_models.chat_model_context import ModelContextRevisionConflictError, ModelContextRunClosedError
from .storage_models.chat_reads import InvalidPageCursor, StalePageCursor
from .storage_models.chat_asset_errors import ChatAssetDeletionError, ChatAssetOwnershipError
from .storage_models.post_turn import PostTurnLeaseLost

DOMAIN_ERRORS: dict[str, type[Exception]] = {error.__name__: error for error in (
    OutreachIntentConflictError, ChatMessageConflictError, ChatTurnConflictError,
    ChatSessionCreationConflict, ChatSessionNotFound, ModelContextRevisionConflictError,
    ModelContextRunClosedError, InvalidPageCursor, StalePageCursor, ChatAssetDeletionError,
    PostTurnLeaseLost, ChatAssetOwnershipError,
)}


def domain_failure(error: Exception) -> StorageResult:
    return StorageResult(error="conflict", domain_error=type(error).__name__, detail=str(error)[:512])


def raise_domain_failure(result: StorageResult) -> None:
    if result.domain_error is None:
        return
    error = DOMAIN_ERRORS.get(result.domain_error)
    if error is None or result.error is None:
        raise ValueError("Invalid storage domain failure")
    raise error(result.detail or "Storage operation was rejected")
