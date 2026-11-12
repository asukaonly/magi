class ChatAssetDeletionError(RuntimeError):
    """Raised when a user-requested managed asset deletion is incomplete."""


class ChatAssetOwnershipError(ValueError):
    """Raised when a message cannot safely claim all referenced asset files."""
